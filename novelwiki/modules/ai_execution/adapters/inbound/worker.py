"""Dedicated host worker for officially authenticated AGY CLI jobs.

Run with ``python -m novelwiki.agy.worker`` under the same OS user/session that
completed the official AGY browser/keyring login. The web process never starts
this worker and never receives AGY credentials.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from novelwiki.platform.observability import audit
from novelwiki.modules.ai_execution.domain.backend import ExecutionBackend, Workload
from novelwiki.kernel.errors import Forbidden, NotFound
from novelwiki.modules.identity.public import Principal
from novelwiki.platform.config import settings

logger = logging.getLogger(__name__)
WORKER_ID = f"agy-{os.getpid()}-{uuid.uuid4().hex[:12]}"
ADVISORY_LOCK_KEY = "novelwiki-agy-subscription-v1"
_runtime = None


def configure_worker_runtime(runtime) -> None:
    global _runtime
    _runtime = runtime


def _configured_runtime():
    if _runtime is None:
        raise RuntimeError("AI Execution worker runtime was not wired by the composition root")
    return _runtime


class _ServiceProxy:
    def __getattr__(self, name):
        return getattr(_configured_runtime().work_service, name)


service = _ServiceProxy()


async def _worker_state():
    return await _configured_runtime().worker_state_factory()


async def _load_user(user_id: int | None) -> dict | None:
    return await (await _worker_state()).load_user(user_id)


async def _write_heartbeat(status: str, preflight: object | None, **details) -> None:
    if preflight is not None:
        details = {**details, "configured_models_present": preflight.healthy,
                   "models": list(preflight.models), "preflight_error_code": preflight.error_code}
    await (await _worker_state()).write_heartbeat(
        worker_id=WORKER_ID,
        status=status,
        version=preflight.version if preflight else None,
        plugin_version=settings.AGY_PLUGIN_VERSION,
        plugin_sha256=preflight.plugin_sha256 if preflight else None,
        details=details,
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
    state = await _worker_state()
    rows = await state.orphan_runs()
    for row in rows:
        pgid, started = row["process_group_id"], row["process_started_at"]
        if pgid and _configured_runtime().process_identity_matches(int(pgid), started):
            await _configured_runtime().terminate_process_group(int(pgid), started_at=started)
        run_id = row["id"]
        workspace = Path(settings.AGY_WORK_DIR) / (row["workspace_relpath"] or "")
        # A complete final manifest may still be committed by the retried handler.
        # Keep it as validating; otherwise the attempt is definitively worker-lost.
        resumable = bool(row["status"] == "validating" and (workspace / "output" / "manifest.json").is_file())
        if resumable:
            continue
        await state.mark_orphan_lost(
            run_id, row["workload"] == "translate_batch"
        )


async def _reauthorize(job: dict, catalog_access) -> tuple[bool, str, dict | None]:
    user = await _load_user(job.get("user_id"))
    if not user:
        return False, "user_missing", None
    if job.get("kind") == "agy_smoke":
        return (user.get("status") == "active" and user.get("role") == "admin"), "admin_smoke", user
    allowed, reason = await _configured_runtime().reauthorize_job(job, user)
    if not allowed:
        return False, reason, user
    if job.get("novel_id") is None:
        return False, "novel_edit_revoked", user
    try:
        await catalog_access.require_editable(
            int(job["novel_id"]),
            Principal.from_user(user),
        )
    except (NotFound, Forbidden):
        return False, "novel_edit_revoked", user
    policy = await _configured_runtime().get_policy(int(user["id"]))
    if not policy:
        return False, "grant_revoked", user
    active = await (await _worker_state()).active_job_count(int(user["id"]))
    if active > int(policy.get("max_concurrent_agy_jobs") or 1):
        return False, "user_concurrency_exceeded", user
    return True, reason, user


async def _handle_codex(job: dict, preflight: object) -> dict:

    class LegacyCodexContext(_AgyExecutionContext):
        execute_codex_job = staticmethod(execute_codex_job)

    return await _configured_runtime().registry_factory().resolve("codex_build")(
        job, preflight, LegacyCodexContext()
    )


async def execute_codex_job(job: dict, preflight):
    """Compatibility seam replaced by Bootstrap in production and tests."""
    raise RuntimeError("Codex AGY execution was not wired")


class _AgyExecutionContext:
    @staticmethod
    async def bail_if_canceled(job_id: int) -> None:
        if await service.is_canceled(job_id):
            raise _configured_runtime().canceled_error()

    set_progress = staticmethod(lambda *args, **kwargs: service.set_progress(*args, **kwargs))


async def _fallback_to_api(job: dict, exc: Exception) -> bool:
    if not job.get("backend_fallback_allowed") or int(job.get("attempts") or 0) < int(job.get("max_attempts") or 0):
        return False
    if job["kind"] == "translate":
        await service.release_translation_reservation_for_fallback(int(job["id"]))
        model = _configured_runtime().model_for(Workload.TRANSLATE_BATCH, ExecutionBackend.API)
    else:
        model = _configured_runtime().model_for(Workload.CODEX_EXTRACT, ExecutionBackend.API)
    changed = await (await _worker_state()).fallback_to_api(
        int(job["id"]), model, settings.JOB_MAX_ATTEMPTS,
        _configured_runtime().safe_error_summary(exc),
    )
    if changed:
        await audit.record("agy.run.fallback_to_api", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                           data={"job_id": int(job["id"]), "failure_code": getattr(exc, "code", "unknown")})
    return bool(changed)


async def _process(job: dict, preflight: object, state: dict, catalog_access) -> None:
    job_id = int(job["id"])
    token = job.get("claim_token")
    stop_hb = asyncio.Event()
    lease_task = asyncio.create_task(_configured_runtime().heartbeat(job_id, token, stop_hb))
    try:
        from novelwiki.modules.ai_execution.application.worker import AgyWorkerService
        registry = _configured_runtime().registry_factory()

        class Operations:
            reauthorize = staticmethod(lambda claimed: _reauthorize(claimed, catalog_access))
            resolve_handler = staticmethod(registry.resolve)
            execution_context = staticmethod(_AgyExecutionContext)
            cancel = staticmethod(service.cancel_job)
            mark_canceled = staticmethod(service.mark_canceled_if_running)
            mark_done = staticmethod(lambda jid, progress: service.mark_done_if_running(jid, progress=progress))
            finalize = staticmethod(lambda jid, ok: service.finalize(jid, success=ok))
            is_canceled = staticmethod(service.is_canceled)
            fallback_to_api = staticmethod(_fallback_to_api)
            fail_or_retry = staticmethod(service.fail_or_retry)
            unsupported_error = staticmethod(lambda: _configured_runtime().agy_error(
                "unsupported AGY job kind", code="agy_artifact_invalid", retryable=False
            ))
            is_canceled_error = staticmethod(_configured_runtime().is_canceled_error)
            error_code = staticmethod(lambda exc: getattr(exc, "code", "unknown"))
            error_summary = staticmethod(_configured_runtime().safe_error_summary)
            provider_wait_code = staticmethod(_configured_runtime().is_provider_wait_code)

            @staticmethod
            async def wait_for_provider(jid, code, summary):
                await service.wait_for_provider(
                    jid, code, summary, settings.AGY_PROVIDER_RETRY_MINUTES
                )

            @staticmethod
            async def record(event, claimed_job, **data):
                await audit.record(event, user_id=claimed_job.get("user_id"),
                                   novel_id=claimed_job.get("novel_id"), data=data)

        await AgyWorkerService(Operations()).process(job, preflight, state)
    finally:
        stop_hb.set()
        try:
            await lease_task
        except Exception:
            pass

async def worker_loop(
    poll_interval: float = 2.0, stop: asyncio.Event | None = None, *, catalog_access
) -> None:
    stop = stop or asyncio.Event()
    state = {"status": "starting", "preflight": None, "job_id": None, "error": None}
    hb = asyncio.create_task(_heartbeat_loop(stop, state))
    worker_state = await _worker_state()
    try:
        locked = await worker_state.acquire_subscription_lock(ADVISORY_LOCK_KEY)
        if not locked:
            state.update(status="standby", error="another AGY worker holds the subscription lock")
            await _write_heartbeat("standby", None, error=state["error"])
            raise RuntimeError("another AGY worker holds the subscription lock")
        await _configured_runtime().release_due_provider_waits()
        await _configured_runtime().recover_stale_leases()
        await _reap_orphans()
        _configured_runtime().validate_work_root().mkdir(parents=True, exist_ok=True, mode=0o700)
        preflight = await _configured_runtime().run_preflight(raise_on_error=False)
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
                    preflight = await _configured_runtime().run_preflight(raise_on_error=False)
                    state.update(preflight=preflight,
                                 status="healthy" if settings.AGY_ENABLED and preflight.healthy else "unhealthy",
                                 error=preflight.error)
                continue
            maintenance += 1
            if maintenance % 30 == 0:
                await _configured_runtime().release_due_provider_waits()
                await _configured_runtime().recover_stale_leases()
                await _configured_runtime().cleanup_expired_workspaces()
            job = await _configured_runtime().claim_next(execution_backend="agy", worker_id=WORKER_ID,
                                   kinds=("translate", "codex_build", "agy_smoke"))
            if job is None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass
                continue
            await _process(job, preflight, state, catalog_access)
    finally:
        try:
            await worker_state.release_subscription_lock(ADVISORY_LOCK_KEY)
        except Exception:
            pass
        stop.set()
        try:
            await hb
        except Exception:
            pass
