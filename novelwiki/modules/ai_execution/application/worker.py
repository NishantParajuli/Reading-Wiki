"""Application orchestration for a claimed AGY job."""
from __future__ import annotations

from typing import Any, Protocol


class AgyWorkerOperations(Protocol):
    async def reauthorize(self, job: dict) -> tuple[bool, str, dict | None]: ...
    def resolve_handler(self, kind: str): ...
    def execution_context(self): ...
    async def cancel(self, job_id: int) -> None: ...
    async def mark_canceled(self, job_id: int) -> None: ...
    async def mark_done(self, job_id: int, progress: dict) -> bool: ...
    async def finalize(self, job_id: int, success: bool) -> None: ...
    async def is_canceled(self, job_id: int) -> bool: ...
    async def wait_for_provider(self, job_id: int, code: str, summary: str) -> None: ...
    async def fallback_to_api(self, job: dict, error: Exception) -> bool: ...
    async def fail_or_retry(self, job: dict, summary: str) -> None: ...
    async def record(self, event: str, job: dict, **data: Any) -> None: ...
    def exception(self, message: str) -> None: ...
    def unsupported_error(self) -> Exception: ...
    def is_canceled_error(self, error: Exception) -> bool: ...
    def error_code(self, error: Exception) -> str: ...
    def error_summary(self, error: Exception) -> str: ...
    def provider_wait_code(self, code: str) -> bool: ...


class AgyWorkerService:
    def __init__(self, operations: AgyWorkerOperations):
        self._ops = operations

    async def process(self, job: dict, preflight: Any, state: dict) -> None:
        job_id = int(job["id"])
        state["job_id"] = job_id
        try:
            allowed, reason, _user = await self._ops.reauthorize(job)
            if not allowed:
                await self._ops.cancel(job_id)
                await self._ops.mark_canceled(job_id)
                await self._ops.record("agy.run.canceled", job, job_id=job_id, reason=reason)
                return
            await self._ops.record(
                "agy.run.started", job, job_id=job_id, kind=job["kind"],
                model=job.get("backend_model"),
            )
            try:
                handler = self._ops.resolve_handler(job["kind"])
            except LookupError:
                handler = None
            if handler is None:
                raise self._ops.unsupported_error()
            progress = await handler(job, preflight, self._ops.execution_context())
            if job["kind"] == "agy_smoke":
                await self._ops.record(
                    "agy.smoke.completed", job, job_id=job_id,
                    version=progress.get("version"), model=progress.get("model"),
                )
            if await self._ops.mark_done(job_id, progress):
                await self._ops.finalize(job_id, True)
                await self._ops.record(
                    "agy.run.completed", job, job_id=job_id, kind=job["kind"]
                )
            else:
                await self._ops.mark_canceled(job_id)
        except Exception as exc:
            self._ops.exception(
                f"AGY {job.get('kind', 'unknown')} job {job_id} raised "
                f"{type(exc).__name__}."
            )
            if self._ops.is_canceled_error(exc):
                await self._ops.mark_canceled(job_id)
                await self._ops.record("agy.run.canceled", job, job_id=job_id)
                return
            code = self._ops.error_code(exc)
            summary = self._ops.error_summary(exc)
            if await self._ops.is_canceled(job_id):
                await self._ops.mark_canceled(job_id)
            elif self._ops.provider_wait_code(code):
                await self._ops.wait_for_provider(job_id, code, summary)
            elif code in {
                "agy_not_authenticated", "agy_permission_blocked", "agy_plugin_invalid",
                "agy_version_unsupported", "agy_model_missing",
            }:
                state.update(status="unhealthy", error=summary)
                await self._ops.wait_for_provider(job_id, code, summary)
            elif not await self._ops.fallback_to_api(job, exc):
                await self._ops.fail_or_retry(job, summary)
            await self._ops.record(
                "agy.run.failed", job, job_id=job_id, failure_code=code,
                attempt=job.get("attempts"),
            )
        finally:
            state["job_id"] = None
