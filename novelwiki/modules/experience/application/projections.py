from __future__ import annotations

from novelwiki.kernel.errors import NotFound
from novelwiki.modules.identity.public import Principal

from .ports import CatalogReadAccess, ExperienceProjectionRepository


class ExperienceProjectionService:
    def __init__(
        self, repository: ExperienceProjectionRepository, catalog: CatalogReadAccess
    ):
        self._repository = repository
        self._catalog = catalog

    async def library_cards(self, principal: Principal) -> list[dict]:
        return await self._repository.library_cards(principal)

    async def novel_detail(self, novel_id: int, principal: Principal) -> dict:
        await self._catalog.require_readable(novel_id, principal)
        result = await self._repository.novel_detail(novel_id, principal)
        if result is None:
            raise NotFound("Novel not found.")
        return result

    async def discover(self, principal: Principal, **filters) -> dict:
        return await self._repository.discover(principal, **filters)

    async def public_profile(self, username: str, principal: Principal) -> dict:
        result = await self._repository.public_profile(username, principal)
        if result is None:
            raise NotFound("User not found.")
        return result
