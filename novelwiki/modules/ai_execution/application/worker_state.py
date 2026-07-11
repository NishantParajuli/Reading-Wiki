from __future__ import annotations

from .ports import AgyWorkerStateRepository


class AgyWorkerStateService:
    def __init__(self, repository: AgyWorkerStateRepository):
        self._repository = repository

    async def load_user(self, user_id: int | None) -> dict | None:
        if user_id is None:
            return None
        return await self._repository.load_user(user_id)

    async def write_heartbeat(self, **fields) -> None:
        await self._repository.write_heartbeat(**fields)

    async def orphan_runs(self) -> list[dict]:
        return await self._repository.orphan_runs()

    async def mark_orphan_lost(self, run_id: int, release_translation: bool) -> None:
        await self._repository.mark_orphan_lost(run_id, release_translation)

    async def active_job_count(self, user_id: int) -> int:
        return await self._repository.active_job_count(user_id)

    async def fallback_to_api(
        self, job_id: int, model: str, max_attempts: int, error: str
    ) -> bool:
        return await self._repository.fallback_to_api(
            job_id, model, max_attempts, error
        )

    async def acquire_subscription_lock(self, key: str) -> bool:
        return await self._repository.acquire_subscription_lock(key)

    async def release_subscription_lock(self, key: str) -> None:
        await self._repository.release_subscription_lock(key)
