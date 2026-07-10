"""Generic durable-job model: CRUD, dedupe, quota finalization, and the state transitions the
worker drives. The heavy lifting (claim/heartbeat/retry loop) lives in ``worker.py``; this module
is the persistence + business layer that both the routes and the worker call.

Job lifecycle::

    queued ──claim──▶ running ──▶ done
       ▲                 │
       └─ (retry / lease-expiry recovery) ─┘
    queued|running ──cancel──▶ canceled
    running ──exhausted retries / crash──▶ failed

Quota semantics (see the report's refund requirements): a job may reserve API budget up front
(``quota_kind`` / ``quota_reserved`` — today only codex_build does). ``finalize`` is called
exactly once at a terminal state and is guarded by ``quota_finalized``:

- success  → the reservation counts as consumed (``quota_consumed := quota_reserved``); no refund.
- failure/cancel → the unconsumed remainder (``reserved - consumed``) is refunded to the user.

API translation meters per chapter as it works. AGY translation reserves the whole pending batch
before subscription work starts, then increments ``quota_consumed`` in the same transaction as
each validated chapter commit. Finalization refunds the untouched remainder exactly once.
"""
from __future__ import annotations

import json
import logging

from novelwiki import audit, quota
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool

logger = logging.getLogger(__name__)

KINDS = ("scrape", "codex_build", "translate", "agy_smoke")
TRIGGER_STATUSES = ("queued",)
ACTIVE_STATUSES = ("queued", "running", "waiting_provider")
TERMINAL_STATUSES = ("done", "failed", "canceled")

_JSON_FIELDS = {"progress", "options"}


class ActiveJobLimitError(RuntimeError):
    pass


class BackendPolicyChangedError(RuntimeError):
    pass


# ── Row (de)serialization ────────────────────────────────────────────────────

def _loads(v):
    """asyncpg returns JSONB as text here (no codec registered) — decode on read."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v


def _row_to_job(row) -> dict:
    job = dict(row)
    for f in _JSON_FIELDS:
        if f in job and job[f] is not None:
            job[f] = _loads(job[f])
    return job


def job_view(job: dict) -> dict:
    """Trim a job row to the shape the API/UI needs."""
    return {
        "id": int(job["id"]),
        "kind": job["kind"],
        "novel_id": int(job["novel_id"]) if job.get("novel_id") is not None else None,
        "user_id": int(job["user_id"]) if job.get("user_id") is not None else None,
        "status": job["status"],
        "stage": job.get("stage"),
        "progress": job.get("progress") or {},
        "options": job.get("options") or {},
        "error": job.get("error"),
        "attempts": int(job.get("attempts") or 0),
        "max_attempts": int(job.get("max_attempts") or 0),
        "backend_requested": job.get("backend_requested") or "auto",
        "execution_backend": job.get("execution_backend") or "api",
        "backend_model": job.get("backend_model"),
        "backend_policy_version": job.get("backend_policy_version"),
        "backend_fallback_allowed": bool(job.get("backend_fallback_allowed")),
        "backend_fallback_from": job.get("backend_fallback_from"),
        "backend_state": job.get("status"),
        "backend_wait_reason": job.get("error") if job.get("status") == "waiting_provider" else None,
        "current_run_id": str(job["current_run_id"]) if job.get("current_run_id") else None,
        "plugin_version": job.get("current_plugin_version") or (
            settings.AGY_PLUGIN_VERSION if (job.get("execution_backend") or "api") == "agy" else None
        ),
        "cancel_requested": job.get("cancel_requested_at") is not None,
        "not_before": job["not_before"].isoformat() if job.get("not_before") else None,
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "updated_at": job["updated_at"].isoformat() if job.get("updated_at") else None,
    }


# ── Create (with idempotent dedupe) ──────────────────────────────────────────

async def find_active(kind: str, idempotency_key: str) -> dict | None:
    """The oldest still-active (queued|running) job for this kind + idempotency key, if any."""
    if not idempotency_key:
        return None
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM jobs
            WHERE kind = $1 AND idempotency_key = $2 AND status = ANY($3::text[])
            ORDER BY created_at ASC LIMIT 1;
            """,
            kind, idempotency_key, list(ACTIVE_STATUSES),
        )
    return _row_to_job(row) if row else None


async def create_job(kind: str, *, novel_id: int | None, user_id: int | None,
                     options: dict | None = None, idempotency_key: str | None = None,
                     quota_kind: str | None = None, quota_reserved: int = 0,
                     max_attempts: int | None = None,
                     backend_requested: str = "auto", execution_backend: str = "api",
                     backend_policy_version: int | None = None,
                     backend_fallback_allowed: bool = False,
                     backend_model: str | None = None) -> tuple[int, bool]:
    """Insert a job, deduping onto an existing active job with the same ``idempotency_key``.

    Returns ``(job_id, created)`` — ``created`` is False when an existing active job was reused,
    so the caller can release any quota it speculatively reserved. Dedupe is race-safe via a
    transaction-scoped advisory lock keyed on ``kind:idempotency_key`` (mirrors the TTS worker).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown job kind: {kind}")
    opts = dict(options or {})
    max_att = int(max_attempts if max_attempts is not None else settings.JOB_MAX_ATTEMPTS)
    key = (idempotency_key or "").strip() or None

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if key:
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2));", "jobs_dedupe", f"{kind}:{key}",
                )
                existing = await conn.fetchval(
                    """
                    SELECT id FROM jobs
                    WHERE kind = $1 AND idempotency_key = $2 AND status = ANY($3::text[])
                    ORDER BY created_at ASC LIMIT 1;
                    """,
                    kind, key, list(ACTIVE_STATUSES),
                )
                if existing is not None:
                    return int(existing), False
            if execution_backend == "agy" and user_id is not None and kind != "agy_smoke":
                # Close the route-level count/create race across web processes.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2));",
                    "agy_user_queue", str(user_id),
                )
                policy = await conn.fetchrow(
                    "SELECT agy_enabled,max_concurrent_agy_jobs FROM user_ai_backend_policies "
                    "WHERE user_id=$1;", user_id,
                )
                if not policy or not policy["agy_enabled"]:
                    raise BackendPolicyChangedError("AGY grant changed before the job was created")
                active = int(await conn.fetchval(
                    """
                    SELECT count(*) FROM jobs WHERE user_id=$1 AND execution_backend='agy'
                      AND status=ANY($2::text[]);
                    """,
                    user_id, list(ACTIVE_STATUSES),
                ) or 0)
                if active >= int(policy["max_concurrent_agy_jobs"]):
                    raise ActiveJobLimitError("per-user AGY job limit is already in use")
            job_id = int(await conn.fetchval(
                """
                INSERT INTO jobs (kind, novel_id, user_id, status, stage, options,
                                  idempotency_key, quota_kind, quota_reserved, max_attempts,
                                  backend_requested, execution_backend, backend_policy_version,
                                  backend_fallback_allowed, backend_model)
                VALUES ($1, $2, $3, 'queued', 'queued', $4, $5, $6, $7, $8,
                        $9, $10, $11, $12, $13)
                RETURNING id;
                """,
                kind, novel_id, user_id, json.dumps(opts), key, quota_kind, int(quota_reserved), max_att,
                backend_requested, execution_backend, backend_policy_version,
                bool(backend_fallback_allowed), backend_model,
            ))
    await audit.record("job.created", user_id=user_id, novel_id=novel_id,
                       data={"job_id": job_id, "kind": kind, "execution_backend": execution_backend,
                             "backend_requested": backend_requested, "backend_model": backend_model})
    await audit.record("ai.backend.resolved", user_id=user_id, novel_id=novel_id,
                       data={"job_id": job_id, "kind": kind, "requested": backend_requested,
                             "resolved": execution_backend, "model": backend_model,
                             "policy_version": backend_policy_version})
    return job_id, True


# ── Read ─────────────────────────────────────────────────────────────────────

async def get_job(job_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT j.*,r.id AS current_run_id,r.plugin_version AS current_plugin_version
            FROM jobs j LEFT JOIN LATERAL (
              SELECT id,plugin_version FROM ai_execution_runs
              WHERE job_id=j.id ORDER BY created_at DESC LIMIT 1
            ) r ON TRUE WHERE j.id=$1;
            """,
            job_id,
        )
    return _row_to_job(row) if row else None


async def list_jobs(*, user_id: int | None = None, kind: str | None = None, status: str | None = None,
                    novel_id: int | None = None, active_only: bool = False, limit: int = 100) -> list[dict]:
    """Filtered listing. ``user_id`` scopes to one requester (None = all, for admins)."""
    conds, args = [], []
    if user_id is not None:
        args.append(user_id); conds.append(f"user_id = ${len(args)}")
    if kind is not None:
        args.append(kind); conds.append(f"kind = ${len(args)}")
    if status is not None:
        args.append(status); conds.append(f"status = ${len(args)}")
    if novel_id is not None:
        args.append(novel_id); conds.append(f"novel_id = ${len(args)}")
    if active_only:
        args.append(list(ACTIVE_STATUSES)); conds.append(f"status = ANY(${len(args)}::text[])")
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    args.append(max(1, min(int(limit), 500)))
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT j.*,r.id AS current_run_id,r.plugin_version AS current_plugin_version
            FROM jobs j LEFT JOIN LATERAL (
              SELECT id,plugin_version FROM ai_execution_runs
              WHERE job_id=j.id ORDER BY created_at DESC LIMIT 1
            ) r ON TRUE {where} ORDER BY j.created_at DESC LIMIT ${len(args)};
            """, *args
        )
    return [_row_to_job(r) for r in rows]


# ── Write / transitions ──────────────────────────────────────────────────────

async def update_job(job_id: int, **fields) -> None:
    """Patch a job row. JSONB fields are json-dumped automatically; ``updated_at`` bumps."""
    if not fields:
        return
    sets, args = [], []
    for k, v in fields.items():
        args.append(json.dumps(v) if k in _JSON_FIELDS and v is not None else v)
        sets.append(f"{k} = ${len(args)}")
    args.append(job_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE jobs SET {', '.join(sets)}, updated_at = now() WHERE id = ${len(args)};", *args
        )


async def set_progress(job_id: int, progress: dict, stage: str | None = None) -> None:
    if stage is not None:
        await update_job(job_id, progress=progress, stage=stage)
    else:
        await update_job(job_id, progress=progress)


async def cancel_job(job_id: int) -> bool:
    """Request cancellation. A queued job is never claimed; a running job stops at its next
    cancellation check. Terminal jobs are left as-is. Returns True if a state change happened.
    Quota is finalized immediately so a worker crash after cancellation cannot strand a reserved
    credit on a terminal-but-unfinalized row."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # A live AGY child needs its lease and running state until the runner kills
        # the process group. API jobs retain the historical immediate/cooperative
        # cancellation behavior.
        row = await conn.fetchrow(
            """
            UPDATE jobs SET
              status = CASE WHEN status='running' AND execution_backend='agy'
                            THEN 'running' ELSE 'canceled' END,
              stage = CASE WHEN status='running' AND execution_backend='agy'
                           THEN 'cancel requested' ELSE 'canceled' END,
              cancel_requested_at = now(),
              claim_token = CASE WHEN status='running' AND execution_backend='agy'
                                 THEN claim_token ELSE NULL END,
              claimed_at = CASE WHEN status='running' AND execution_backend='agy'
                                THEN claimed_at ELSE NULL END,
              updated_at=now()
            WHERE id=$1 AND status IN ('queued','running','waiting_provider')
            RETURNING id, status;
            """,
            job_id,
        )
    if row is None:
        return False
    if row["status"] == "canceled":
        await finalize(job_id, success=False)
        await audit.record("job.canceled", data={"job_id": job_id})
    else:
        await audit.record("agy.run.cancel_requested", data={"job_id": job_id})
    return True


async def is_canceled(job_id: int) -> bool:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status, cancel_requested_at FROM jobs WHERE id = $1;", job_id)
    return bool(row and (row["status"] == "canceled" or row["cancel_requested_at"] is not None))


async def mark_canceled_if_running(job_id: int) -> bool:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE jobs SET status='canceled', stage='canceled', claim_token=NULL,
              claimed_at=NULL, updated_at=now()
            WHERE id=$1 AND status='running' AND cancel_requested_at IS NOT NULL
            RETURNING id;
            """,
            job_id,
        )
    if row:
        await finalize(job_id, success=False)
        await audit.record("job.canceled", data={"job_id": job_id})
    return row is not None


async def mark_done_if_running(job_id: int, progress: dict | None = None) -> bool:
    """Terminal success, but only if a concurrent cancel hasn't won. Returns True if it marked done."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        if progress is not None:
            row = await conn.fetchrow(
                "UPDATE jobs SET status='done', stage='done', error=NULL, progress=$2, "
                "claim_token=NULL, claimed_at=NULL, updated_at=now() "
                "WHERE id=$1 AND status='running' RETURNING id;",
                job_id, json.dumps(progress),
            )
        else:
            row = await conn.fetchrow(
                "UPDATE jobs SET status='done', stage='done', error=NULL, "
                "claim_token=NULL, claimed_at=NULL, updated_at=now() "
                "WHERE id=$1 AND status='running' RETURNING id;",
                job_id,
            )
    return row is not None


async def fail_or_retry(job: dict, error: str) -> None:
    """A running attempt crashed. Retry (back to ``queued``) while attempts remain, else fail
    terminally and finalize quota. Guarded on ``status='running'`` so a concurrent cancel wins;
    if the job was cancelled underneath us, we finalize as a cancel instead."""
    job_id = int(job["id"])
    err = str(error)[:4000]
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE jobs SET
              status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
              stage  = CASE WHEN attempts >= max_attempts THEN 'failed'
                            ELSE 'retrying after error (attempt ' || attempts || '/' || max_attempts || ')' END,
              error = $2, claim_token = NULL, claimed_at = NULL,
              not_before = CASE WHEN attempts >= max_attempts THEN NULL
                                ELSE now() + make_interval(secs => LEAST(300, power(2, attempts)::int * 5)) END,
              updated_at = now()
            WHERE id = $1 AND status = 'running'
            RETURNING status;
            """,
            job_id, err,
        )
    if row is None:
        # Status wasn't 'running' — a cancel landed first. Finalize the cancel's refund.
        await finalize(job_id, success=False)
        return
    if row["status"] == "failed":
        logger.error(f"Job {job_id} failed permanently: {err}")
        await finalize(job_id, success=False)
        await audit.record("job.failed", data={"job_id": job_id, "error": err})
    else:
        logger.warning(f"Job {job_id} will retry: {err}")


async def wait_for_provider(job_id: int, failure_code: str, error: str, minutes: int) -> bool:
    """Park a running AGY job without holding a lease or burning tight retries."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE jobs SET status='waiting_provider', stage='waiting for AGY provider',
              error=$2, not_before=now() + make_interval(mins => $3),
              claim_token=NULL, claimed_at=NULL, updated_at=now()
            WHERE id=$1 AND status='running' RETURNING id;
            """,
            job_id, str(error)[:4000], max(1, int(minutes)),
        )
    if row:
        await audit.record("agy.run.waiting_provider", data={"job_id": job_id, "failure_code": failure_code})
    return row is not None


async def retry_waiting(*, job_id: int | None = None) -> int:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        if job_id is None:
            result = await conn.execute(
                "UPDATE jobs SET status='queued', stage='queued', not_before=NULL, error=NULL, updated_at=now() "
                "WHERE status='waiting_provider';"
            )
        else:
            result = await conn.execute(
                "UPDATE jobs SET status='queued', stage='queued', not_before=NULL, error=NULL, updated_at=now() "
                "WHERE id=$1 AND status='waiting_provider';", job_id,
            )
    return int(result.rsplit(" ", 1)[-1])


async def increment_quota_consumed(job_id: int, units: int = 1, *, conn=None) -> None:
    """Record a reserved unit as committed. May be called inside the domain transaction."""
    if units <= 0:
        return
    query = """
        UPDATE jobs SET quota_consumed = quota_consumed + $2, updated_at=now()
        WHERE id=$1 AND quota_finalized=FALSE
          AND quota_consumed + $2 <= quota_reserved;
    """
    if conn is not None:
        result = await conn.execute(query, job_id, int(units))
    else:
        pool = await get_db_pool()
        async with pool.acquire() as own:
            result = await own.execute(query, job_id, int(units))
    if result.endswith("0"):
        raise RuntimeError("job quota reservation is missing, finalized, or exhausted")


async def release_translation_reservation_for_fallback(job_id: int) -> None:
    """Refund AGY translation's unused reservation before API meters remaining chapters."""
    await finalize(job_id, success=False)


async def finalize(job_id: int, *, success: bool) -> None:
    """Settle a terminal job's quota exactly once (guarded by ``quota_finalized``). On success the
    reservation is treated as consumed; otherwise the unconsumed remainder is refunded."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE jobs SET
              quota_finalized = TRUE,
              quota_consumed  = CASE
                WHEN $2 AND NOT (execution_backend='agy' AND kind='translate') THEN quota_reserved
                ELSE quota_consumed END,
              updated_at = now()
            WHERE id = $1 AND quota_finalized = FALSE
            RETURNING user_id, novel_id, quota_kind, quota_reserved, quota_consumed;
            """,
            job_id, success,
        )
    if row is None:
        return  # already finalized
    kind = row["quota_kind"]
    refund_n = max(0, int(row["quota_reserved"] or 0) - int(row["quota_consumed"] or 0))
    if kind and refund_n > 0 and row["user_id"] is not None:
        refunded = await quota.refund(int(row["user_id"]), kind, refund_n)
        if refunded:
            logger.info(f"Job {job_id}: refunded {refunded} {kind} unit(s) to user {row['user_id']}.")
            await audit.record("quota.refund", user_id=int(row["user_id"]), novel_id=row["novel_id"],
                               data={"job_id": job_id, "kind": kind, "units": refunded})
