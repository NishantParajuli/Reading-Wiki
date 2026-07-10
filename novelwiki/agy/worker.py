"""Dedicated host worker for officially authenticated AGY CLI jobs.

Run with ``python -m novelwiki.agy.worker`` under the same OS user/session that
completed the official AGY browser/keyring login. The web process never starts
this worker and never receives AGY credentials.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from novelwiki import audit
from novelwiki.agy.codex import execute_codex_job
from novelwiki.agy.errors import AgyCanceled, AgyError, PROVIDER_WAIT_CODES, safe_error_summary
from novelwiki.agy.preflight import PreflightResult, run_preflight
from novelwiki.agy.runner import process_identity_matches, terminate_process_group
from novelwiki.agy.translation import execute_translation_job
from novelwiki.agy.workspace import cleanup_expired_workspaces, validate_work_root
from novelwiki.ai_backend.policy import get_policy, model_for, reauthorize_job
from novelwiki.ai_backend.types import ExecutionBackend, Workload
from novelwiki.auth.access import can_edit, fetch_novel
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool, init_db_pool
from novelwiki.jobs import service
from novelwiki.jobs.claims import claim_next
from novelwiki.jobs.worker import _heartbeat, _recover_stale_leases, _release_due_provider_waits

logger = logging.getLogger(__name__)
WORKER_ID = f"agy-{os.getpid()}-{uuid.uuid4().hex[:12]}"
ADVISORY_LOCK_KEY = "novelwiki-agy-subscription-v1"


async def _load_user(user_id: int | None) -> dict | None:
    if user_id is None:
        return None
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id=$1;", user_id)
    return dict(row) if row else None


async def _write_heartbeat(status: str, preflight: PreflightResult | None, **details) -> None:
    if preflight is not None:
        details = {**details, "configured_models_present": preflight.healthy,
                   "models": list(preflight.models), "preflight_error_code": preflight.error_code}
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ai_worker_heartbeats
              (worker_id,backend,status,version,plugin_version,plugin_sha256,details,heartbeat_at,started_at)
            VALUES ($1,'agy',$2,$3,$4,$5,$6,now(),now())
            ON CONFLICT (worker_id) DO UPDATE SET status=EXCLUDED.status,
              version=EXCLUDED.version,plugin_version=EXCLUDED.plugin_version,
              plugin_sha256=EXCLUDED.plugin_sha256,details=EXCLUDED.details,heartbeat_at=now();
            """,
            WORKER_ID, status, preflight.version if preflight else None,
            settings.AGY_PLUGIN_VERSION, preflight.plugin_sha256 if preflight else None,
            json.dumps(details),
        )


async def _heartbeat_loop(stop: asyncio.Event, state: dict) -> None:
    while not stop.is_set():
        try:
            await _write_heartbeat(state.get("status", "starting"), state.get("preflight"),
                                   current_job_id=state.get("job_id"), error=state.get("error"))
        except Exception as exc:
            logger.debug("AGY worker heartbeat failed: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


async def _reap_orphans() -> None:
    """Kill verified stale process groups before any new subscription work starts."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id,job_id,workload,status,workspace_relpath,process_group_id,process_started_at
            FROM ai_execution_runs
            WHERE backend='agy' AND status IN ('preparing','running','validating');
            """
        )
    for row in rows:
        pgid, started = row["process_group_id"], row["process_started_at"]
        if pgid and process_identity_matches(int(pgid), started):
            await terminate_process_group(int(pgid), started_at=started)
        run_id = row["id"]
        workspace = Path(settings.AGY_WORK_DIR) / (row["workspace_relpath"] or "")
        # A complete final manifest may still be committed by the retried handler.
        # Keep it as validating; otherwise the attempt is definitively worker-lost.
        resumable = bool(row["status"] == "validating" and (workspace / "output" / "manifest.json").is_file())
        if resumable:
            continue
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ai_execution_runs SET status='worker_lost',failure_code='worker_lost',
                  error_summary='Worker exited before a complete artifact was ready.',finished_at=now()
                WHERE id=$1 AND status IN ('preparing','running','validating');
                """,
                run_id,
            )
            if row["workload"] == "translate_batch":
                await conn.execute(
                    """
                    UPDATE chapters SET translation_status='failed',translation_run_id=NULL
                    WHERE translation_run_id=$1 AND translation_status='translating';
                    """,
                    run_id,
                )


async def _reauthorize(job: dict) -> tuple[bool, str, dict | None]:
    user = await _load_user(job.get("user_id"))
    if not user:
        return False, "user_missing", None
    if job.get("kind") == "agy_smoke":
        return (user.get("status") == "active" and user.get("role") == "admin"), "admin_smoke", user
    allowed, reason = await reauthorize_job(job, user)
    if not allowed:
        return False, reason, user
    novel = await fetch_novel(int(job["novel_id"])) if job.get("novel_id") is not None else None
    if not novel or not can_edit(novel, user):
        return False, "novel_edit_revoked", user
    policy = await get_policy(int(user["id"]))
    if not policy:
        return False, "grant_revoked", user
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        active = int(await conn.fetchval(
            """
            SELECT count(*) FROM jobs WHERE user_id=$1 AND execution_backend='agy'
              AND status IN ('queued','running','waiting_provider');
            """,
            user["id"],
        ) or 0)
    if active > int(policy.get("max_concurrent_agy_jobs") or 1):
        return False, "user_concurrency_exceeded", user
    return True, reason, user


async def _handle_codex(job: dict, preflight: PreflightResult) -> dict:
    from novelwiki.ingest.chunk import chunk_all_chapters
    from novelwiki.ingest.embed import embed_missing_chunks
    from novelwiki.retrieval.bm25 import get_bm25_manager

    opts = job.get("options") or {}
    job_id, novel_id = int(job["id"]), int(job["novel_id"])
    await service.set_progress(job_id, {"step": 1, "steps": 4, "stage": "chunking"}, stage="chunking")
    await chunk_all_chapters(novel_id, force=bool(opts.get("force")),
                             from_chapter=opts.get("from_chapter"), to_chapter=opts.get("to_chapter"))
    if await service.is_canceled(job_id):
        raise AgyCanceled()
    await service.set_progress(job_id, {"step": 2, "steps": 4, "stage": "embedding"}, stage="embedding")
    await embed_missing_chunks(novel_id, from_chapter=opts.get("from_chapter"), to_chapter=opts.get("to_chapter"))
    if await service.is_canceled(job_id):
        raise AgyCanceled()
    extracted = await execute_codex_job(job, preflight)
    if await service.is_canceled(job_id):
        raise AgyCanceled()
    await service.set_progress(job_id, {"step": 4, "steps": 4, **extracted}, stage="indexing")
    await get_bm25_manager(novel_id).rebuild()
    return {"step": 4, "steps": 4, **extracted}


async def _fallback_to_api(job: dict, exc: Exception) -> bool:
    if not job.get("backend_fallback_allowed") or int(job.get("attempts") or 0) < int(job.get("max_attempts") or 0):
        return False
    if job["kind"] == "translate":
        await service.release_translation_reservation_for_fallback(int(job["id"]))
        model = model_for(Workload.TRANSLATE_BATCH, ExecutionBackend.API)
    else:
        model = model_for(Workload.CODEX_EXTRACT, ExecutionBackend.API)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        changed = await conn.fetchrow(
            """
            UPDATE jobs SET execution_backend='api',backend_fallback_from='agy',backend_model=$2,
              backend_fallback_allowed=FALSE,status='queued',stage='AGY failed; switching to API',
              attempts=0,max_attempts=$3,error=$4,claim_token=NULL,claimed_at=NULL,
              not_before=NULL,cancel_requested_at=NULL,updated_at=now()
            WHERE id=$1 AND status='running' RETURNING id;
            """,
            int(job["id"]), model, settings.JOB_MAX_ATTEMPTS,
            safe_error_summary(exc),
        )
    if changed:
        await audit.record("agy.run.fallback_to_api", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                           data={"job_id": int(job["id"]), "failure_code": getattr(exc, "code", "unknown")})
    return bool(changed)


async def _process(job: dict, preflight: PreflightResult, state: dict) -> None:
    job_id = int(job["id"])
    state["job_id"] = job_id
    token = job.get("claim_token")
    stop_hb = asyncio.Event()
    lease_task = asyncio.create_task(_heartbeat(job_id, token, stop_hb))
    try:
        allowed, reason, _user = await _reauthorize(job)
        if not allowed:
            await service.cancel_job(job_id)
            await service.mark_canceled_if_running(job_id)
            await audit.record("agy.run.canceled", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                               data={"job_id": job_id, "reason": reason})
            return
        await audit.record("agy.run.started", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                           data={"job_id": job_id, "kind": job["kind"], "model": job.get("backend_model")})
        if job["kind"] == "translate":
            progress = await execute_translation_job(job, preflight)
        elif job["kind"] == "codex_build":
            progress = await _handle_codex(job, preflight)
        elif job["kind"] == "agy_smoke":
            from novelwiki.agy.smoke import run_smoke_test
            progress = await run_smoke_test(job_id)
            await audit.record("agy.smoke.completed", user_id=job.get("user_id"), data={
                "job_id": job_id, "version": progress.get("version"), "model": progress.get("model"),
            })
        else:
            raise AgyError("unsupported AGY job kind", code="agy_artifact_invalid", retryable=False)
        if await service.mark_done_if_running(job_id, progress=progress):
            await service.finalize(job_id, success=True)
            await audit.record("agy.run.completed", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                               data={"job_id": job_id, "kind": job["kind"]})
        else:
            await service.mark_canceled_if_running(job_id)
    except AgyCanceled:
        await service.mark_canceled_if_running(job_id)
        await audit.record("agy.run.canceled", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                           data={"job_id": job_id})
    except Exception as exc:
        code = getattr(exc, "code", "unknown")
        if await service.is_canceled(job_id):
            await service.mark_canceled_if_running(job_id)
        elif code in PROVIDER_WAIT_CODES:
            await service.wait_for_provider(job_id, code, safe_error_summary(exc), settings.AGY_PROVIDER_RETRY_MINUTES)
        elif code in {"agy_not_authenticated", "agy_permission_blocked", "agy_plugin_invalid",
                      "agy_version_unsupported", "agy_model_missing"}:
            state.update(status="unhealthy", error=safe_error_summary(exc))
            await service.wait_for_provider(job_id, code, safe_error_summary(exc), settings.AGY_PROVIDER_RETRY_MINUTES)
        elif not await _fallback_to_api(job, exc):
            await service.fail_or_retry(job, safe_error_summary(exc))
        await audit.record("agy.run.failed", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                           data={"job_id": job_id, "failure_code": code, "attempt": job.get("attempts")})
    finally:
        state["job_id"] = None
        stop_hb.set()
        try:
            await lease_task
        except Exception:
            pass


async def worker_loop(poll_interval: float = 2.0, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    state = {"status": "starting", "preflight": None, "job_id": None, "error": None}
    hb = asyncio.create_task(_heartbeat_loop(stop, state))
    pool = await get_db_pool()
    lock_conn = await pool.acquire()
    try:
        locked = await lock_conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1));", ADVISORY_LOCK_KEY)
        if not locked:
            state.update(status="standby", error="another AGY worker holds the subscription lock")
            await _write_heartbeat("standby", None, error=state["error"])
            raise RuntimeError("another AGY worker holds the subscription lock")
        await _release_due_provider_waits()
        await _recover_stale_leases()
        await _reap_orphans()
        validate_work_root().mkdir(parents=True, exist_ok=True, mode=0o700)
        preflight = await run_preflight(raise_on_error=False)
        state["preflight"] = preflight
        state["status"] = "healthy" if settings.AGY_ENABLED and preflight.healthy else (
            "disabled" if not settings.AGY_ENABLED else "unhealthy")
        state["error"] = preflight.error
        await audit.record("agy.worker.healthy" if preflight.healthy else "agy.worker.preflight_failed",
                           data={"worker_id": WORKER_ID, "error_code": preflight.error_code,
                                 "version": preflight.version, "plugin_sha256": preflight.plugin_sha256})
        maintenance = 0
        while not stop.is_set():
            if not settings.AGY_ENABLED or not preflight.healthy or state["status"] == "unhealthy":
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except asyncio.TimeoutError:
                    preflight = await run_preflight(raise_on_error=False)
                    state.update(preflight=preflight,
                                 status="healthy" if settings.AGY_ENABLED and preflight.healthy else "unhealthy",
                                 error=preflight.error)
                continue
            maintenance += 1
            if maintenance % 30 == 0:
                await _release_due_provider_waits()
                await _recover_stale_leases()
                await cleanup_expired_workspaces()
            job = await claim_next(execution_backend="agy", worker_id=WORKER_ID,
                                   kinds=("translate", "codex_build", "agy_smoke"))
            if job is None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass
                continue
            await _process(job, preflight, state)
    finally:
        try:
            await lock_conn.execute("SELECT pg_advisory_unlock(hashtext($1));", ADVISORY_LOCK_KEY)
        except Exception:
            pass
        await pool.release(lock_conn)
        stop.set()
        try:
            await hb
        except Exception:
            pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await init_db_pool()
    try:
        await worker_loop()
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
