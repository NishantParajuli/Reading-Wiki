from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .ports import WorkerStateRepository


@dataclass(frozen=True)
class LeaseRecovery:
    job_id: int
    action: str


class WorkerStateService:
    """Application policy for generic-worker persistence and lease recovery."""

    def __init__(self, repository: WorkerStateRepository):
        self._repository = repository

    async def load_user(self, user_id: int | None) -> dict | None:
        if user_id is None:
            return None
        return await self._repository.load_user(user_id)

    async def pending_translations(
        self,
        novel_id: int,
        from_chapter: float | None,
        to_chapter: float | None,
        force: bool,
    ) -> list[float]:
        return await self._repository.pending_translations(
            novel_id, from_chapter, to_chapter, force
        )

    async def renew_lease(self, job_id: int, token: str | None) -> None:
        if token:
            await self._repository.renew_lease(job_id, token)

    async def recover_stale_leases(
        self, lease: timedelta
    ) -> list[LeaseRecovery]:
        recoveries: list[LeaseRecovery] = []
        for row in await self._repository.stale_leases(lease):
            job_id = int(row["id"])
            if row["cancel_requested_at"] is not None:
                if await self._repository.cancel_stale_lease(job_id, lease):
                    recoveries.append(LeaseRecovery(job_id, "canceled"))
                continue
            if int(row["attempts"]) >= int(row["max_attempts"]):
                if await self._repository.fail_stale_lease(job_id, lease):
                    recoveries.append(LeaseRecovery(job_id, "failed"))
            elif await self._repository.requeue_stale_lease(job_id, lease):
                recoveries.append(LeaseRecovery(job_id, "requeued"))
        return recoveries

    async def release_due_provider_waits(self) -> None:
        await self._repository.release_due_provider_waits()
