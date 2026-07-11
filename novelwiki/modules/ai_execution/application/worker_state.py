from __future__ import annotations

from .ports import (
    AgyIdentityPort, AgyReadingRecoveryPort, AgyWorkerStateRepository, AgyWorkPort,
)


class AgyWorkerStateService:
    def __init__(
        self, repository: AgyWorkerStateRepository, identity: AgyIdentityPort,
        reading: AgyReadingRecoveryPort, work: AgyWorkPort,
    ):
        self._repository = repository
        self._identity = identity
        self._reading = reading
        self._work = work

    async def load_user(self, user_id: int | None) -> dict | None:
        if user_id is None:
            return None
        return await self._identity.load_user(user_id)

    async def write_heartbeat(self, **fields) -> None:
        await self._repository.write_heartbeat(**fields)

    async def orphan_runs(self) -> list[dict]:
        return await self._repository.orphan_runs()

    async def mark_orphan_lost(self, run_id: int, release_translation: bool) -> None:
        await self._repository.mark_orphan_lost(run_id)
        if release_translation:
            await self._reading.reset_staged_translations(run_id, "failed")

    async def active_job_count(self, user_id: int) -> int:
        return await self._work.active_job_count(user_id)

    async def fallback_to_api(
        self, job_id: int, model: str, max_attempts: int, error: str
    ) -> bool:
        return await self._work.fallback_to_api(
            job_id, model, max_attempts, error
        )

    async def acquire_subscription_lock(self, key: str) -> bool:
        return await self._repository.acquire_subscription_lock(key)

    async def release_subscription_lock(self, key: str) -> None:
        await self._repository.release_subscription_lock(key)
