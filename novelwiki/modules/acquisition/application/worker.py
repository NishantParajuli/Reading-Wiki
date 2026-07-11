"""Application-level state-machine dispatch for durable import jobs."""
from __future__ import annotations

from typing import Any, Protocol


class ImportWorkerOperations(Protocol):
    async def owner_can_spend(self, job: dict) -> bool: ...
    async def parse(self, job: dict) -> None: ...
    async def ocr(self, job: dict) -> None: ...
    async def commit(self, job: dict) -> None: ...
    async def fail(self, job_id: int, error: str) -> None: ...
    def exception(self, message: str) -> None: ...


class ImportWorkerService:
    """Owns stage authorization, dispatch and failure translation."""

    def __init__(self, operations: ImportWorkerOperations):
        self._ops = operations

    async def process(self, job: dict) -> None:
        job_id = int(job["id"])
        status = job["status"]
        try:
            if status == "parsing":
                if not await self._ops.owner_can_spend(job):
                    await self._ops.fail(job_id, "Verify your email before importing files.")
                    return
                await self._ops.parse(job)
            elif status == "ocr_running":
                if not await self._ops.owner_can_spend(job):
                    await self._ops.fail(job_id, "Verify your email before running OCR.")
                    return
                await self._ops.ocr(job)
            elif status == "commit_running":
                await self._ops.commit(job)
        except Exception as exc:
            self._ops.exception(f"Import job {job_id} crashed during '{status}'.")
            await self._ops.fail(job_id, f"{type(exc).__name__}: {exc}")
