"""Dedicated host worker for officially authenticated subscription CLI jobs.

Bootstrap configures one process for AGY or OpenAI Codex. Each runs under the OS
user that completed the provider's official login; the web process never starts
these workers and never receives their credentials.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from novelwiki.platform.observability import audit
from novelwiki.platform.observability.logging import log_context, log_event
from novelwiki.modules.ai_execution.domain.backend import ExecutionBackend, Workload
from novelwiki.kernel.errors import Forbidden, NotFound
from novelwiki.modules.identity.public import Principal
from novelwiki.platform.config import settings

logger = logging.getLogger(__name__)
WORKER_ID = f"agy-{os.getpid()}-{uuid.uuid4().hex[:12]}"
ADVISORY_LOCK_KEY = "novelwiki-agy-subscription-v1"
_runtime = None

_WORKLOAD_NAMES = {
    "translate": "translate_batch",
    "codex_build": "codex_extract",
    "agy_smoke": "smoke_test",
    "openai_codex_smoke": "smoke_test",
}


def configure_worker_runtime(runtime) -> None:
    global _runtime, WORKER_ID, ADVISORY_LOCK_KEY
    _runtime = runtime
    WORKER_ID = f"{runtime.worker_type}-{os.getpid()}-{uuid.uuid4().hex[:12]}"
    ADVISORY_LOCK_KEY = runtime.advisory_lock_key


def _configured_runtime():
    if _runtime is None:
        raise RuntimeError("AI Execution worker runtime was not wired by the composition root")
    return _runtime


def _provider_label() -> str:
    return "OpenAI Codex" if _configured_runtime().backend == "openai_codex" else "AGY"


def _event(suffix: str) -> str:
    return f"{_configured_runtime().backend}.{suffix}"


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
        plugin_version=_configured_runtime().contract_version,
        plugin_sha256=preflight.plugin_sha256 if preflight else None,
        details=details,
    )


async def _heartbeat_loop(stop: asyncio.Event, state: dict) -> None:
    while not stop.is_set():
        try:
            await _write_heartbeat(state.get("status", "starting"), state.get("preflight"),
                                   current_job_id=state.get("job_id"), error=state.get("error"))
        except Exception as exc:
            log_event(
                logger, logging.WARNING, _event("worker_heartbeat_failed"),
                f"Could not persist the {_provider_label()} worker heartbeat.",
                error_type=type(exc).__name__, error=str(exc),
                worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
            )
        else:
            log_event(
                logger, logging.DEBUG, _event("worker_heartbeat"),
                f"Persisted the {_provider_label()} worker heartbeat.",
                worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
                worker_status=state.get("status"), current_job_id=state.get("job_id"),
            )
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
        workspace = _configured_runtime().work_root / (row["workspace_relpath"] or "")
        # A complete final manifest may still be committed by the retried handler.
        # Keep it as validating; otherwise the attempt is definitively worker-lost.
        resumable = bool(row["status"] == "validating" and (workspace / "output" / "manifest.json").is_file())
        if resumable:
            log_event(
                logger, logging.WARNING, _event("orphan_run_resumable"),
                f"Retained validating orphan {_provider_label()} run {run_id} for job {row['job_id']}.",
                worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
                job_system="generic",
                job_id=row["job_id"], job_kind=row.get("workload"), ai_run_id=run_id,
                process_group_id=pgid,
            )
            continue
        await state.mark_orphan_lost(
            run_id, row["workload"] == "translate_batch"
        )
        log_event(
            logger, logging.ERROR, _event("orphan_run_lost"),
            f"Marked orphan {_provider_label()} run {run_id} for job {row['job_id']} as worker-lost.",
            worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
            job_system="generic",
            job_id=row["job_id"], agy_workload=row["workload"], ai_run_id=run_id,
            process_group_id=pgid,
        )


async def _reauthorize(job: dict, catalog_access) -> tuple[bool, str, dict | None]:
    user = await _load_user(job.get("user_id"))
    if not user:
        return False, "user_missing", None
    if job.get("kind") == _configured_runtime().smoke_kind:
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
    if active > int(policy.get(_configured_runtime().concurrency_policy_key) or 1):
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

    @staticmethod
    async def set_progress(job_id: int, progress: dict, stage: str | None = None) -> None:
        await service.set_progress(job_id, progress, stage=stage)
        if settings.LOG_JOB_PROGRESS:
            log_event(
                logger, logging.INFO, _event("job_progress"),
                f"{_provider_label()} job {job_id} reported progress"
                f"{f' in {stage}' if stage else ''}.",
                stage=stage, progress=progress,
            )


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
        await audit.record(_event("run.fallback_to_api"), user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                           data={"job_id": int(job["id"]), "failure_code": getattr(exc, "code", "unknown")})
    return bool(changed)


async def _process(job: dict, preflight: object, state: dict, catalog_access) -> None:
    job_id = int(job["id"])
    token = job.get("claim_token")
    workload = _WORKLOAD_NAMES.get(job.get("kind"), job.get("kind"))
    options = job.get("options") or {}
    with log_context(
        worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID, job_system="generic",
        job_id=job_id, job_kind=job.get("kind"), ai_workload=workload,
        user_id=job.get("user_id"), novel_id=job.get("novel_id"),
        attempt=job.get("attempts"), max_attempts=job.get("max_attempts"),
        execution_backend=_configured_runtime().backend,
        backend_requested=job.get("backend_requested"),
        backend_model=job.get("backend_model"),
    ):
        started = time.monotonic()
        log_event(
            logger, logging.INFO, _event("job_claimed"),
            f"{_provider_label()} worker claimed {workload} job {job_id} "
            f"(attempt {job.get('attempts')}/{job.get('max_attempts')}).",
            status=job.get("status"), stage=job.get("stage"),
            force=bool(options.get("force")),
            from_chapter=options.get("from_chapter"),
            to_chapter=options.get("to_chapter"),
        )
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
                    "unsupported subscription job kind",
                    code=f"{_configured_runtime().backend}_artifact_invalid",
                    retryable=False,
                ))
                is_canceled_error = staticmethod(_configured_runtime().is_canceled_error)
                error_code = staticmethod(lambda exc: getattr(exc, "code", "unknown"))
                error_summary = staticmethod(_configured_runtime().safe_error_summary)
                provider_wait_code = staticmethod(_configured_runtime().is_provider_wait_code)

                @staticmethod
                async def wait_for_provider(jid, code, summary):
                    await service.wait_for_provider(
                        jid, code, summary, _configured_runtime().provider_retry_minutes
                    )

                @staticmethod
                def exception(message):
                    log_event(
                        logger, logging.ERROR, _event("run_exception"), message,
                        exc_info=True,
                    )

                @staticmethod
                async def record(event, claimed_job, **data):
                    level = logging.ERROR if event.endswith("failed") else (
                        logging.WARNING if event.endswith("canceled") else logging.INFO
                    )
                    log_event(
                        logger, level, event,
                        f"{_provider_label()} {workload} job {job_id}: {event}.", **data,
                    )
                    await audit.record(event, user_id=claimed_job.get("user_id"),
                                       novel_id=claimed_job.get("novel_id"), data=data)

            await AgyWorkerService(
                Operations(), _configured_runtime().backend
            ).process(job, preflight, state)
        finally:
            stop_hb.set()
            try:
                await lease_task
            except Exception:
                pass
            try:
                finished = await service.get_job(job_id)
            except Exception:
                log_event(
                    logger, logging.WARNING, _event("outcome_lookup_failed"),
                    f"Could not load the final state for {_provider_label()} {workload} job {job_id}.",
                    exc_info=True,
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
            else:
                status = (finished or {}).get("status", "missing")
                level = logging.ERROR if status == "failed" else (
                    logging.WARNING if status in {"queued", "waiting_provider", "canceled"}
                    else logging.INFO
                )
                log_event(
                    logger, level, _event("job_attempt_finished"),
                    f"Finished {_provider_label()} {workload} job {job_id} attempt with status {status}.",
                    status=status, stage=(finished or {}).get("stage"),
                    progress=(finished or {}).get("progress"),
                    retry_scheduled=status == "queued",
                    not_before=(finished or {}).get("not_before"),
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )

async def worker_loop(
    poll_interval: float = 2.0, stop: asyncio.Event | None = None, *, catalog_access
) -> None:
    stop = stop or asyncio.Event()
    state = {"status": "starting", "preflight": None, "job_id": None, "error": None}
    hb = asyncio.create_task(_heartbeat_loop(stop, state))
    worker_state = await _worker_state()
    log_event(
        logger, logging.INFO, "worker.started", "Dedicated subscription worker started.",
        worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
        execution_backend=_configured_runtime().backend,
        poll_interval_seconds=poll_interval,
        subscription_backend_enabled=_configured_runtime().enabled,
        configured_models={
            "translate_batch": _configured_runtime().model_translate,
            "codex_extract": _configured_runtime().model_codex,
        },
    )
    try:
        locked = await worker_state.acquire_subscription_lock(ADVISORY_LOCK_KEY)
        if not locked:
            state.update(
                status="standby",
                error=f"another {_provider_label()} worker holds the subscription lock",
            )
            await _write_heartbeat("standby", None, error=state["error"])
            log_event(
                logger, logging.ERROR, _event("subscription_lock_unavailable"),
                f"Dedicated {_provider_label()} worker is in standby because another process holds the subscription lock.",
                worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
            )
            raise RuntimeError(state["error"])
        log_event(
            logger, logging.INFO, _event("subscription_lock_acquired"),
            f"Dedicated {_provider_label()} worker acquired the subscription lock.",
            worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
        )
        await _configured_runtime().release_due_provider_waits()
        await _configured_runtime().recover_stale_leases(
            worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID
        )
        await _reap_orphans()
        _configured_runtime().validate_work_root().mkdir(parents=True, exist_ok=True, mode=0o700)
        preflight = await _configured_runtime().run_preflight(raise_on_error=False)
        state["preflight"] = preflight
        state["status"] = "healthy" if _configured_runtime().enabled and preflight.healthy else (
            "disabled" if not _configured_runtime().enabled else "unhealthy")
        state["error"] = preflight.error
        await audit.record(_event("worker.healthy") if preflight.healthy else _event("worker.preflight_failed"),
                           data={"worker_id": WORKER_ID, "error_code": preflight.error_code,
                                 "version": preflight.version, "plugin_sha256": preflight.plugin_sha256})
        log_event(
            logger, logging.INFO if preflight.healthy else logging.ERROR,
            _event("preflight_succeeded") if preflight.healthy else _event("preflight_failed"),
            f"{_provider_label()} preflight completed with worker status {state['status']}.",
            worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
            worker_status=state["status"],
            subscription_backend_enabled=_configured_runtime().enabled,
            healthy=preflight.healthy,
            runner_version=preflight.version, error_code=preflight.error_code,
            error=preflight.error, plugin_version=_configured_runtime().contract_version,
            plugin_sha256=preflight.plugin_sha256,
            configured_models_present=preflight.healthy,
            available_models=list(preflight.models),
        )
        maintenance = 0
        while not stop.is_set():
            if not _configured_runtime().enabled or not preflight.healthy or state["status"] == "unhealthy":
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except asyncio.TimeoutError:
                    previous_status = state["status"]
                    preflight = await _configured_runtime().run_preflight(raise_on_error=False)
                    state.update(preflight=preflight,
                                 status="healthy" if _configured_runtime().enabled and preflight.healthy else (
                                     "disabled" if not _configured_runtime().enabled else "unhealthy"
                                 ),
                                 error=preflight.error)
                    log_event(
                        logger, logging.INFO if preflight.healthy else logging.WARNING,
                        _event("preflight_refreshed"),
                        f"Refreshed {_provider_label()} preflight; worker status is {state['status']}.",
                        worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
                        previous_status=previous_status, worker_status=state["status"],
                        healthy=preflight.healthy, error_code=preflight.error_code,
                        error=preflight.error, runner_version=preflight.version,
                    )
                continue
            maintenance += 1
            if maintenance % 30 == 0:
                await _configured_runtime().release_due_provider_waits()
                await _configured_runtime().recover_stale_leases(
                    worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID
                )
                await _configured_runtime().cleanup_expired_workspaces()
                log_event(
                    logger, logging.DEBUG, _event("maintenance_completed"),
                    f"Completed {_provider_label()} provider-wait, lease, and workspace maintenance.",
                    worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
                )
            job = await _configured_runtime().claim_next(
                execution_backend=_configured_runtime().backend,
                worker_id=WORKER_ID,
                kinds=("translate", "codex_build", _configured_runtime().smoke_kind),
            )
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
            log_event(
                logger, logging.WARNING, _event("subscription_lock_release_failed"),
                f"Could not explicitly release the {_provider_label()} subscription lock.",
                exc_info=True, worker_type=_configured_runtime().worker_type,
                worker_id=WORKER_ID,
            )
        stop.set()
        try:
            await hb
        except Exception:
            pass
        log_event(
            logger, logging.INFO, "worker.stopped",
            f"Dedicated {_provider_label()} worker stopped.",
            worker_type=_configured_runtime().worker_type, worker_id=WORKER_ID,
            execution_backend=_configured_runtime().backend,
            worker_status=state.get("status"),
        )
