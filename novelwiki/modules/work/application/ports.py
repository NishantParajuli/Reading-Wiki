from __future__ import annotations

from datetime import timedelta
from typing import Protocol


class WorkRepository(Protocol):
    async def get_job(self, job_id: int) -> dict | None: ...

    async def list_jobs(
        self, *, user_id: int | None = None, kind: str | None = None,
        status: str | None = None, novel_id: int | None = None,
        active_only: bool = False, limit: int = 100,
    ) -> list[dict]: ...

    async def cancel_job(self, job_id: int) -> bool: ...

    def job_view(self, job: dict) -> dict: ...


class JobMetadataPort(Protocol):
    async def current(self, job_ids: set[int]) -> dict[int, dict]: ...


class JobObservationPort(Protocol):
    def observe(self, jobs: list[dict]) -> None: ...


class WorkerStateRepository(Protocol):
    async def renew_lease(self, job_id: int, token: str) -> None: ...

    async def stale_leases(self, lease: timedelta) -> list[dict]: ...

    async def cancel_stale_lease(self, job_id: int, lease: timedelta) -> bool: ...

    async def fail_stale_lease(self, job_id: int, lease: timedelta) -> bool: ...

    async def requeue_stale_lease(self, job_id: int, lease: timedelta) -> bool: ...

    async def release_due_provider_waits(self) -> None: ...


class WorkerIdentityPort(Protocol):
    async def load_user(self, user_id: int) -> dict | None: ...


class WorkerTranslationPort(Protocol):
    async def translation_range(
        self, novel_id: int, start: float | None, end: float | None, force: bool
    ) -> list[float]: ...
