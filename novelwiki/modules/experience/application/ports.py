from typing import Protocol

from novelwiki.modules.identity.public import Principal


class ExperienceProjectionRepository(Protocol):
    async def library_cards(self, principal: Principal) -> list[dict]: ...
    async def novel_detail(self, novel_id: int, principal: Principal) -> dict | None: ...
    async def discover(
        self, principal: Principal, *, q: str | None, language: str | None,
        tag: str | None, translation: str | None, has_codex: bool | None,
        has_audio: bool | None, freshness: str | None, sort: str,
        offset: int, limit: int,
    ) -> dict: ...
    async def public_profile(
        self, username: str, principal: Principal
    ) -> dict | None: ...


class CatalogReadAccess(Protocol):
    async def require_readable(self, novel_id: int, principal: Principal) -> object: ...
