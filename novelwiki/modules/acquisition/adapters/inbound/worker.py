"""Durable Acquisition polling/lease adapter with explicit dependencies."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from novelwiki.modules.acquisition.application import import_worker as jobs
from novelwiki.modules.acquisition.application.worker import ImportWorkerService
from novelwiki.platform.observability.logging import log_context, log_event

logger = logging.getLogger(__name__)

TRIGGER_STATUSES = jobs.TRIGGER_STATUSES
_MARKER_RESUME = jobs._MARKER_RESUME


@dataclass(frozen=True)
class ImportWorkerConfig:
    lease_timeout_seconds: int
    heartbeat_seconds: int
    upload_session_ttl_hours: int
    maintenance_interval_seconds: float = 60.0


class ImportWorkerAdapter:
    """Own polling, leases, maintenance tasks, and process lifecycle."""

    def __init__(self, runtime, config: ImportWorkerConfig):
        self._runtime = runtime
        self._config = config
        self._worker_id = f"import-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self._last_maintenance = 0.0
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def _repository(self):
        return await self._runtime.import_repository()

    async def _recover_stale_leases(self) -> None:
        lease = timedelta(seconds=self._config.lease_timeout_seconds)
        repository = await self._repository()
        for markers, trigger in _MARKER_RESUME:
            result = await repository.recover_stale_leases(markers, trigger, lease)
            if result and not result.endswith(" 0"):
                log_event(
                    logger, logging.WARNING, "import_job.leases_recovered",
                    f"Recovered orphaned import jobs back to {trigger}.",
                    worker_type="import", worker_id=self._worker_id,
                    job_system="import", recovery_status=trigger,
                    recovered_jobs=int(result.rsplit(" ", 1)[-1]),
                )

    async def _cleanup_stale_uploads(self) -> None:
        ttl = timedelta(hours=self._config.upload_session_ttl_hours)
        repository = await self._repository()
        removed = 0
        for job_id in await repository.stale_upload_ids(ttl):
            if not await repository.delete_stale_upload(job_id, ttl):
                continue
            try:
                self._runtime.cleanup_import_job(job_id)
            except Exception as exc:
                log_event(
                    logger, logging.WARNING, "import_job.cleanup_failed",
                    f"Database cleanup of abandoned import upload {job_id} succeeded, "
                    "but its files could not be removed.",
                    exc_info=True, worker_type="import", worker_id=self._worker_id,
                    job_system="import", job_id=job_id,
                )
            removed += 1
        if removed:
            log_event(
                logger, logging.INFO, "import_job.uploads_cleaned",
                f"Cleaned up {removed} abandoned import upload session(s).",
                worker_type="import", worker_id=self._worker_id,
                job_system="import", removed_jobs=removed,
            )

    async def _run_maintenance(self, force: bool = False) -> None:
        now = time.monotonic()
        if (
            not force
            and now - self._last_maintenance
            < self._config.maintenance_interval_seconds
        ):
            return
        self._last_maintenance = now
        await self._recover_stale_leases()
        await self._cleanup_stale_uploads()

    async def _reactivate_paused(self) -> None:
        if await self._runtime.gemini_budget_remaining() > 0:
            await (await self._repository()).reactivate_paused()

    async def _claim_next(self) -> dict | None:
        row = await (await self._repository()).claim_next(
            TRIGGER_STATUSES, self._worker_id
        )
        return jobs._row_to_job(row) if row else None

    async def _renew_lease(self, job_id: int, token: str | None) -> None:
        if token:
            await (await self._repository()).renew_lease(job_id, token)

    async def _heartbeat(
        self, job_id: int, token: str | None, stop: asyncio.Event
    ) -> None:
        interval = max(5, self._config.heartbeat_seconds)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self._renew_lease(job_id, token)
            except Exception as exc:
                log_event(
                    logger, logging.WARNING, "worker.lease_heartbeat_failed",
                    f"Could not renew the lease for import job {job_id}.",
                    error_type=type(exc).__name__, error=str(exc),
                )
            else:
                log_event(
                    logger, logging.DEBUG, "worker.lease_heartbeat",
                    f"Renewed the lease for import job {job_id}.",
                )

    async def _process(self, job: dict) -> None:
        job_id = int(job["id"])
        options = job.get("options") or {}
        with log_context(
            worker_type="import", worker_id=self._worker_id, job_system="import",
            job_id=job_id, job_kind=f"import_{job.get('format', 'unknown')}",
            job_format=job.get("format"), user_id=job.get("user_id"),
            novel_id=job.get("novel_id"), batch_id=options.get("batch_id"),
        ):
            started = time.monotonic()
            log_event(
                logger, logging.INFO, "import_job.started",
                f"Starting {job.get('format', 'unknown')} import job {job_id} "
                f"at state {job.get('status')}.",
                status=job.get("status"), stage=job.get("stage"),
                auto_commit=bool(options.get("auto_commit")),
                group_series=bool(options.get("group_series")),
                gemini_first=bool(options.get("gemini_first")),
            )
            stop_heartbeat = asyncio.Event()
            heartbeat = asyncio.create_task(
                self._heartbeat(job_id, job.get("claim_token"), stop_heartbeat)
            )
            runtime = self._runtime

            class Operations:
                owner_can_spend = staticmethod(
                    lambda value: jobs._job_owner_can_spend(value, runtime)
                )
                parse = staticmethod(lambda value: jobs.do_parse(value, runtime=runtime))
                ocr = staticmethod(lambda value: jobs.do_ocr(value, runtime=runtime))
                commit = staticmethod(lambda value: jobs.do_commit(value, runtime=runtime))
                fail = staticmethod(
                    lambda identifier, error: jobs.fail_job(
                        identifier, error, runtime=runtime
                    )
                )

                @staticmethod
                def exception(message):
                    log_event(
                        logger, logging.ERROR, "import_job.crashed", message,
                        exc_info=True,
                    )

            try:
                await ImportWorkerService(Operations()).process(job)
            finally:
                stop_heartbeat.set()
                try:
                    await heartbeat
                except Exception:
                    pass
                try:
                    row = await (await self._repository()).get_job(job_id)
                    finished = jobs._row_to_job(row) if row else None
                except Exception:
                    log_event(
                        logger, logging.WARNING, "import_job.outcome_lookup_failed",
                        f"Could not load the final state for import job {job_id}.",
                        exc_info=True,
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                    )
                else:
                    status = (finished or {}).get("status", "missing")
                    level = logging.ERROR if status == "failed" else (
                        logging.WARNING if status in {"ocr_paused", "canceled"}
                        else logging.INFO
                    )
                    log_event(
                        logger, level, "import_job.attempt_finished",
                        f"Finished {job.get('format', 'unknown')} import job {job_id} "
                        f"attempt with status {status}.",
                        status=status, stage=(finished or {}).get("stage"),
                        progress=(finished or {}).get("progress"),
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                    )

    async def worker_loop(self, poll_interval: float = 2.0) -> None:
        self._runtime.ensure_import_dirs()
        try:
            await self._run_maintenance(force=True)
        except Exception as exc:
            log_event(
                logger, logging.WARNING, "worker.maintenance_failed",
                "Import worker startup maintenance failed.", exc_info=True,
                worker_type="import", worker_id=self._worker_id,
            )
        log_event(
            logger, logging.INFO, "worker.started", "Import worker started.",
            worker_type="import", worker_id=self._worker_id,
            job_system="import", poll_interval_seconds=poll_interval,
            lease_timeout_seconds=self._config.lease_timeout_seconds,
            heartbeat_seconds=self._config.heartbeat_seconds,
            upload_session_ttl_hours=self._config.upload_session_ttl_hours,
        )
        while not self._stop.is_set():
            try:
                await self._reactivate_paused()
                await self._run_maintenance()
                job = await self._claim_next()
                if job is not None:
                    await self._process(job)
                    continue
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=poll_interval
                    )
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                break
            except Exception:
                log_event(
                    logger, logging.ERROR, "worker.loop_failed",
                    "Import worker loop failed.", exc_info=True,
                    worker_type="import", worker_id=self._worker_id,
                    job_system="import",
                )
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=poll_interval
                    )
                except asyncio.TimeoutError:
                    pass
        log_event(
            logger, logging.INFO, "worker.stopped", "Import worker stopped.",
            worker_type="import", worker_id=self._worker_id, job_system="import",
        )

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self.worker_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None
