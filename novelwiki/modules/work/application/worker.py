"""Application orchestration for one claimed durable work job."""
from __future__ import annotations

from typing import Any, Protocol


class WorkWorkerOperations(Protocol):
    def resolve_handler(self, kind: str): ...
    def execution_context(self): ...
    async def fail_or_retry(self, job: dict, error: str) -> None: ...
    async def finalize(self, job_id: int, success: bool) -> None: ...
    async def mark_done(self, job_id: int, progress: dict | None) -> bool: ...
    async def record(self, event: str, job: dict, **data: Any) -> None: ...
    def info(self, message: str) -> None: ...
    def exception(self, message: str) -> None: ...
    def is_canceled_error(self, error: Exception) -> bool: ...


class WorkWorkerService:
    def __init__(self, operations: WorkWorkerOperations):
        self._ops = operations

    async def process(self, job: dict) -> None:
        job_id = int(job["id"])
        kind = job["kind"]
        try:
            handler = self._ops.resolve_handler(kind)
        except LookupError:
            handler = None
        try:
            if handler is None:
                await self._ops.fail_or_retry(job, f"Unknown job kind '{kind}'.")
                return
            try:
                progress = await handler(job, self._ops.execution_context())
            except Exception as exc:
                if not self._ops.is_canceled_error(exc):
                    raise
                self._ops.info(f"Job {job_id} ({kind}) canceled mid-run.")
                await self._ops.finalize(job_id, False)
                return
            if await self._ops.mark_done(job_id, progress):
                await self._ops.finalize(job_id, True)
                self._ops.info(f"Job {job_id} ({kind}) done.")
                await self._ops.record("job.done", job, job_id=job_id, kind=kind)
            else:
                await self._ops.finalize(job_id, False)
        except Exception as exc:
            self._ops.exception(f"Job {job_id} ({kind}) crashed.")
            await self._ops.fail_or_retry(job, f"{type(exc).__name__}: {exc}")
