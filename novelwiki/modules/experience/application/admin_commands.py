"""Consumer-owned ports and orchestration for cross-owner admin commands."""
from __future__ import annotations

from typing import Any, Protocol


class AiAdminPort(Protocol):
    async def get_policy(self, user_id: int) -> dict | None: ...
    async def upsert_policy(self, user_id: int, policy: dict, admin_id: int) -> dict: ...
    async def delete_policy(self, user_id: int, admin_id: int) -> bool: ...
    async def worker_available(self) -> bool: ...


class WorkAdminPort(Protocol):
    async def retry_waiting(self) -> int: ...
    async def create_smoke(self, admin_id: int) -> tuple[int, bool]: ...


class AdminAuditPort(Protocol):
    async def record(self, event: str, user_id: int, data: dict) -> None: ...


class ExperienceAdminCommands:
    def __init__(self, ai: AiAdminPort, work: WorkAdminPort, audit: AdminAuditPort):
        self._ai = ai
        self._work = work
        self._audit = audit

    async def get_policy(self, user_id: int) -> dict | None:
        return await self._ai.get_policy(user_id)

    async def put_policy(self, user_id: int, policy: dict, admin_id: int) -> dict:
        return await self._ai.upsert_policy(user_id, policy, admin_id)

    async def delete_policy(self, user_id: int, admin_id: int) -> bool:
        return await self._ai.delete_policy(user_id, admin_id)

    async def worker_available(self) -> bool:
        return await self._ai.worker_available()

    async def retry_waiting(self, admin_id: int) -> int:
        count = await self._work.retry_waiting()
        await self._audit.record("agy.run.retry_waiting", admin_id, {"jobs": count})
        return count

    async def queue_smoke(self, admin_id: int) -> tuple[int, bool]:
        return await self._work.create_smoke(admin_id)
