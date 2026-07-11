from __future__ import annotations

from datetime import timedelta
from typing import Protocol


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
