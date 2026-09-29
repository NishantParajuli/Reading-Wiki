"""Per-user, write-only account connection settings."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain.account_cookies import cookie_metadata, normalize_novelpia_cookies


class AccountCookieRepository(Protocol):
    async def read(self, user_id: int) -> tuple[list[dict], datetime | None]: ...
    async def replace(self, user_id: int, cookies: list[dict]) -> datetime: ...
    async def delete(self, user_id: int) -> None: ...


class AccountCookieService:
    def __init__(self, repository: AccountCookieRepository):
        self._repository = repository

    async def status(self, user_id: int) -> dict:
        cookies, updated_at = await self._repository.read(user_id)
        return cookie_metadata(cookies, updated_at)

    async def replace(self, user_id: int, export: object) -> dict:
        cookies = normalize_novelpia_cookies(export)
        updated_at = await self._repository.replace(user_id, cookies)
        return cookie_metadata(cookies, updated_at)

    async def delete(self, user_id: int) -> dict:
        await self._repository.delete(user_id)
        return cookie_metadata([])
