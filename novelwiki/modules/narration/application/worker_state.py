from __future__ import annotations

from .ports import NarrationWorkerIdentityPort, NarrationWorkerRepository


class NarrationWorkerState:
    def __init__(
        self, repository: NarrationWorkerRepository,
        identity: NarrationWorkerIdentityPort,
    ):
        self._repository = repository
        self._identity = identity

    async def create_job(self, *args, **kwargs):
        return await self._repository.create_job(*args, **kwargs)

    async def get_job(self, job_id: int):
        return await self._repository.get_job(job_id)

    async def active_chapter_job(self, **criteria):
        return await self._repository.active_chapter_job(**criteria)

    async def active_book_job(self, *args, **kwargs):
        return await self._repository.active_book_job(*args, **kwargs)

    async def update_job(self, job_id: int, fields: dict):
        await self._repository.update_job(job_id, fields)

    async def cancel_job(self, job_id: int):
        await self._repository.cancel_job(job_id)

    async def status(self, job_id: int):
        return await self._repository.status(job_id)

    async def load_user(self, user_id: int | None):
        return None if user_id is None else await self._identity.load_user(user_id)

    async def find_audio(self, **criteria):
        return await self._repository.find_audio(**criteria)

    async def upsert_audio(self, **audio):
        await self._repository.upsert_audio(**audio)

    def target_lock(self, key: str):
        return self._repository.target_lock(key)

    async def requeue_interrupted(self):
        return await self._repository.requeue_interrupted()

    async def claim_next(self, trigger_statuses: tuple[str, ...]):
        return await self._repository.claim_next(trigger_statuses)
