"""Durable worker for generic background jobs (scrape / codex build / translation).

Mirrors the import + TTS workers (novelwiki/importer/jobs.py, novelwiki/tts/worker.py): job state
lives in the ``jobs`` table and a single DB-polled background task (started from the app lifespan)
advances jobs across process restarts. This is what lets scrape/codex/translation survive a deploy
after quota was already reserved — the work that used to run in fire-and-forget ``BackgroundTasks``.

Claiming is atomic AND leased: ``_claim_next`` moves ``queued`` → ``running`` in one
``UPDATE … FOR UPDATE SKIP LOCKED``, increments ``attempts``, and stamps the claiming worker's
opaque token + ``claimed_at``. ``running`` is not a trigger status, so a claimed job leaves the
queue the instant it's claimed — two workers can never run the same job. While it works the worker
heartbeats ``claimed_at``; ``_recover_stale_leases`` only reclaims a job whose lease has gone
unrenewed past the timeout (i.e. the owning worker is provably gone), retrying it or failing it once
its attempts are exhausted. There is deliberately no "requeue everything on boot" step.

Cancellation is cooperative: a route flips the job to ``canceled`` and the running handler notices
between stages/chapters and unwinds, keeping any work already finished. Quota is finalized (refunded
if unconsumed) exactly once at every terminal state — see ``service.finalize``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import timedelta

from novelwiki.platform.observability import audit
from novelwiki.platform.observability.logging import log_context, log_event
from novelwiki.platform.config import settings
from novelwiki.modules.work.application import WorkerStateService

logger = logging.getLogger(__name__)

# Opaque per-process identity stamped on claimed jobs — freshly minted each start, so a restarted
# worker never mistakes a previous incarnation's live-looking claim for its own.
_WORKER_ID = f"api-{os.getpid()}-{uuid.uuid4().hex[:12]}"

_MAINTENANCE_INTERVAL_SECONDS = 60.0
_last_maintenance = 0.0

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
_runtime = None


def configure_worker_runtime(runtime) -> None:
    global _runtime
    _runtime = runtime


def _configured_runtime():
    if _runtime is None:
        raise RuntimeError("Work worker runtime was not wired by the composition root")
    return _runtime


async def _worker_state() -> WorkerStateService:
    return await _configured_runtime().worker_state_factory()


# ── User + cancellation helpers ──────────────────────────────────────────────

async def _load_user(user_id: int | None) -> dict | None:
    return await (await _worker_state()).load_user(user_id)


class _Canceled(Exception):
    """Raised by a handler's cancel check to unwind cleanly to the canceled terminal state."""


async def _bail_if_canceled(job_id: int) -> None:
    if await _configured_runtime().service.is_canceled(job_id):
        raise _Canceled()


async def _pending_translations(novel_id: int, frm, to, force: bool) -> list[float]:
    return await (await _worker_state()).pending_translations(
        novel_id, frm, to, force
    )


class _ExecutionContext:
    bail_if_canceled = staticmethod(_bail_if_canceled)
    load_user = staticmethod(_load_user)
    pending_translations = staticmethod(_pending_translations)

    @staticmethod
    async def update_job(job_id: int, **fields) -> None:
        await _configured_runtime().service.update_job(job_id, **fields)
        if settings.LOG_JOB_PROGRESS and ({"status", "stage", "progress"} & fields.keys()):
            log_event(
                logger, logging.INFO, "job.progress",
                f"Updated background job {job_id} state.",
                status=fields.get("status"), stage=fields.get("stage"),
                progress=fields.get("progress"),
            )

    @staticmethod
    async def set_progress(job_id: int, progress: dict, stage: str | None = None) -> None:
        await _configured_runtime().service.set_progress(job_id, progress, stage=stage)
        if settings.LOG_JOB_PROGRESS:
            log_event(
                logger, logging.INFO, "job.progress",
                f"Background job {job_id} reported progress"
                f"{f' in {stage}' if stage else ''}.",
                stage=stage, progress=progress,
            )


# ── Claim / lease / recovery ─────────────────────────────────────────────────

async def _claim_next() -> dict | None:
    """Atomically claim the oldest queued job → ``running``, bump attempts, and stamp this worker's
    lease. The marker is not a trigger status, so the job leaves the queue the instant it's claimed."""
    return await _configured_runtime().claim_next(
        execution_backend="api", worker_id=_WORKER_ID
    )


async def _renew_lease(job_id: int, token: str | None) -> None:
    await (await _worker_state()).renew_lease(job_id, token)


async def _heartbeat(job_id: int, token: str | None, stop: asyncio.Event) -> None:
    interval = max(5, settings.JOB_WORKER_HEARTBEAT_SECONDS)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await _renew_lease(job_id, token)
        except Exception as e:
            log_event(
                logger, logging.WARNING, "worker.lease_heartbeat_failed",
                f"Could not renew the lease for background job {job_id}.",
                error_type=type(e).__name__, error=str(e),
            )
        else:
            log_event(
                logger, logging.DEBUG, "worker.lease_heartbeat",
                f"Renewed the lease for background job {job_id}.",
            )


async def _recover_stale_leases(
    *, worker_type: str = "api", worker_id: str | None = None
) -> None:
    """Reclaim ``running`` jobs whose lease expired (the owning worker crashed/was killed). Multi-worker
    safe: a live worker heartbeats its claim, so a job it is actively processing never looks reclaimable.
    A reclaimed job is retried while attempts remain, else failed once and quota-finalized."""
    lease = timedelta(seconds=settings.JOB_LEASE_TIMEOUT_SECONDS)
    recoveries = await (await _worker_state()).recover_stale_leases(lease)
    for recovery in recoveries:
        job_id = recovery.job_id
        recovered = await _configured_runtime().service.get_job(job_id)
        with log_context(
            worker_type=worker_type, worker_id=worker_id or _WORKER_ID,
            job_system="generic",
            job_id=job_id, job_kind=(recovered or {}).get("kind"),
            user_id=(recovered or {}).get("user_id"),
            novel_id=(recovered or {}).get("novel_id"),
        ):
            if recovery.action == "canceled":
                await _configured_runtime().service.finalize(job_id, success=False)
                log_event(
                    logger, logging.WARNING, "job.lease_recovered",
                    f"Canceled {(recovered or {}).get('kind', 'background')} job {job_id} "
                    "after its lease expired with cancellation requested.",
                    recovery_action="canceled", reason="lease_expired_after_cancel",
                )
                await audit.record(
                    "job.canceled",
                    data={"job_id": job_id, "reason": "lease_expired_after_cancel"},
                )
            elif recovery.action == "failed":
                log_event(
                    logger, logging.ERROR, "job.lease_recovered",
                    f"Failed {(recovered or {}).get('kind', 'background')} job {job_id} "
                    "after its lease expired and attempts were exhausted.",
                    recovery_action="failed", reason="lease_expired",
                    attempts=(recovered or {}).get("attempts"),
                    max_attempts=(recovered or {}).get("max_attempts"),
                )
                await _configured_runtime().service.finalize(job_id, success=False)
                await audit.record(
                    "job.failed", data={"job_id": job_id, "reason": "lease_expired"}
                )
            else:
                log_event(
                    logger, logging.WARNING, "job.lease_recovered",
                    f"Requeued orphaned {(recovered or {}).get('kind', 'background')} "
                    f"job {job_id} after its lease expired.",
                    recovery_action="requeued", reason="lease_expired",
                    attempts=(recovered or {}).get("attempts"),
                    max_attempts=(recovered or {}).get("max_attempts"),
                )


async def _release_due_provider_waits() -> None:
    """A provider-wait row has no lease; make due rows claimable again."""
    await (await _worker_state()).release_due_provider_waits()


async def _run_maintenance(force: bool = False) -> None:
    global _last_maintenance
    now = time.monotonic()
    if not force and (now - _last_maintenance) < _MAINTENANCE_INTERVAL_SECONDS:
        return
    _last_maintenance = now
    await _release_due_provider_waits()
    await _recover_stale_leases()


# ── Process one job ──────────────────────────────────────────────────────────

async def _process(job: dict) -> None:
    job_id = int(job["id"])
    token = job.get("claim_token")
    registry = _configured_runtime().registry_factory()
    options = job.get("options") or {}
    context = {
        "worker_type": "api", "worker_id": _WORKER_ID, "job_system": "generic",
        "job_id": job_id, "job_kind": job.get("kind"),
        "user_id": job.get("user_id"), "novel_id": job.get("novel_id"),
        "attempt": job.get("attempts"), "max_attempts": job.get("max_attempts"),
        "execution_backend": job.get("execution_backend") or "api",
        "backend_requested": job.get("backend_requested"),
        "backend_model": job.get("backend_model"),
    }
    with log_context(**context):
        started = time.monotonic()
        log_event(
            logger, logging.INFO, "job.started",
            f"Starting {job['kind']} job {job_id} "
            f"(attempt {job.get('attempts')}/{job.get('max_attempts')}).",
            initial_stage=job.get("stage"), force=bool(options.get("force")),
            source_id=options.get("source_id"), max_chapters=options.get("max_chapters"),
            from_chapter=options.get("from_chapter"), to_chapter=options.get("to_chapter"),
            seed_from_codex=options.get("seed_from_codex"),
        )
        stop_hb = asyncio.Event()
        heartbeat = asyncio.create_task(_heartbeat(job_id, token, stop_hb))
        try:
            from novelwiki.modules.work.application.worker import WorkWorkerService

            class Operations:
                resolve_handler = staticmethod(registry.resolve)
                execution_context = staticmethod(_ExecutionContext)
                fail_or_retry = staticmethod(_configured_runtime().service.fail_or_retry)
                finalize = staticmethod(lambda jid, ok: _configured_runtime().service.finalize(jid, success=ok))
                mark_done = staticmethod(lambda jid, progress: _configured_runtime().service.mark_done_if_running(jid, progress=progress))
                is_canceled_error = staticmethod(lambda exc: isinstance(exc, _Canceled))

                @staticmethod
                def info(message):
                    log_event(logger, logging.INFO, "job.lifecycle", message)

                @staticmethod
                def exception(message):
                    log_event(
                        logger, logging.ERROR, "job.crashed", message, exc_info=True
                    )

                @staticmethod
                async def record(event, claimed_job, **data):
                    log_event(
                        logger, logging.INFO, event,
                        f"{claimed_job.get('kind', 'Background')} job {job_id}: {event}.",
                        **data,
                    )
                    await audit.record(event, user_id=claimed_job.get("user_id"),
                                       novel_id=claimed_job.get("novel_id"), data=data)

            await WorkWorkerService(Operations()).process(job)
        finally:
            stop_hb.set()
            try:
                await heartbeat
            except Exception:
                pass
            try:
                finished = await _configured_runtime().service.get_job(job_id)
            except Exception:
                log_event(
                    logger, logging.WARNING, "job.outcome_lookup_failed",
                    f"Could not load the final state for {job['kind']} job {job_id}.",
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
                    logger, level, "job.attempt_finished",
                    f"Finished attempt {job.get('attempts')} for {job['kind']} job {job_id} "
                    f"with status {status}.",
                    status=status, stage=(finished or {}).get("stage"),
                    progress=(finished or {}).get("progress"),
                    retry_scheduled=status == "queued",
                    not_before=(finished or {}).get("not_before"),
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )


# ── Worker loop ──────────────────────────────────────────────────────────────

async def worker_loop(poll_interval: float = 2.0) -> None:
    try:
        await _run_maintenance(force=True)
    except Exception as e:
        log_event(
            logger, logging.WARNING, "worker.maintenance_failed",
            "Generic jobs worker startup maintenance failed.", exc_info=True,
            worker_type="api", worker_id=_WORKER_ID,
        )
    log_event(
        logger, logging.INFO, "worker.started", "Generic jobs worker started.",
        worker_type="api", worker_id=_WORKER_ID, poll_interval_seconds=poll_interval,
        lease_timeout_seconds=settings.JOB_LEASE_TIMEOUT_SECONDS,
        heartbeat_seconds=settings.JOB_WORKER_HEARTBEAT_SECONDS,
    )
    while not _stop.is_set():
        try:
            await _run_maintenance()
            job = await _claim_next()
            if job is None:
                try:
                    await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass
                continue
            await _process(job)
        except asyncio.CancelledError:
            break
        except Exception:
            log_event(
                logger, logging.ERROR, "worker.loop_failed",
                "Generic jobs worker loop failed.", exc_info=True,
                worker_type="api", worker_id=_WORKER_ID,
            )
            try:
                await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
    log_event(
        logger, logging.INFO, "worker.stopped", "Generic jobs worker stopped.",
        worker_type="api", worker_id=_WORKER_ID,
    )


def start_worker() -> None:
    """Launch the background jobs worker (idempotent). Called from the FastAPI lifespan."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    _stop.clear()
    _worker_task = asyncio.create_task(worker_loop())


async def stop_worker() -> None:
    global _worker_task
    _stop.set()
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except (asyncio.CancelledError, Exception):
            pass
        _worker_task = None
