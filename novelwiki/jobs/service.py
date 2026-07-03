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

Translation is *not* pre-reserved here: it meters per chapter as it actually translates (via
``quota.try_reserve`` inside ``translate_chapter``), so a cancelled batch keeps the chapters it
finished charged and never over-charges for ones it didn't reach.
"""
from __future__ import annotations

import json
import logging

from novelwiki import audit, quota
from novelwiki.db.connection import get_db_pool

logger = logging.getLogger(__name__)

KINDS = ("scrape", "codex_build", "translate")
TRIGGER_STATUSES = ("queued",)
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("done", "failed", "canceled")

_JSON_FIELDS = {"progress", "options"}


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
                     max_attempts: int | None = None) -> tuple[int, bool]:
    """Insert a job, deduping onto an existing active job with the same ``idempotency_key``.

    Returns ``(job_id, created)`` — ``created`` is False when an existing active job was reused,
    so the caller can release any quota it speculatively reserved. Dedupe is race-safe via a
    transaction-scoped advisory lock keyed on ``kind:idempotency_key`` (mirrors the TTS worker).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown job kind: {kind}")
    opts = dict(options or {})
    from novelwiki.config.settings import settings
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
            job_id = int(await conn.fetchval(
                """
                INSERT INTO jobs (kind, novel_id, user_id, status, stage, options,
                                  idempotency_key, quota_kind, quota_reserved, max_attempts)
                VALUES ($1, $2, $3, 'queued', 'queued', $4, $5, $6, $7, $8)
                RETURNING id;
                """,
                kind, novel_id, user_id, json.dumps(opts), key, quota_kind, int(quota_reserved), max_att,
            ))
    await audit.record("job.created", user_id=user_id, novel_id=novel_id,
                       data={"job_id": job_id, "kind": kind})
    return job_id, True


# ── Read ─────────────────────────────────────────────────────────────────────

async def get_job(job_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1;", job_id)
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
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ${len(args)};", *args
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
        row = await conn.fetchrow(
            "UPDATE jobs SET status='canceled', stage='canceled', "
            "claim_token=NULL, claimed_at=NULL, updated_at=now() "
            "WHERE id = $1 AND status IN ('queued','running') RETURNING id;",
            job_id,
        )
    if row is None:
        return False
    await finalize(job_id, success=False)
    await audit.record("job.canceled", data={"job_id": job_id})
    return True


async def is_canceled(job_id: int) -> bool:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        st = await conn.fetchval("SELECT status FROM jobs WHERE id = $1;", job_id)
    return st == "canceled"


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
              error = $2, claim_token = NULL, claimed_at = NULL, updated_at = now()
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


async def finalize(job_id: int, *, success: bool) -> None:
    """Settle a terminal job's quota exactly once (guarded by ``quota_finalized``). On success the
    reservation is treated as consumed; otherwise the unconsumed remainder is refunded."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE jobs SET
              quota_finalized = TRUE,
              quota_consumed  = CASE WHEN $2 THEN quota_reserved ELSE quota_consumed END,
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
