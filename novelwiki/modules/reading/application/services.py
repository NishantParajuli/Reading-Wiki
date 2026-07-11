from __future__ import annotations

from novelwiki.kernel.errors import NotFound
from novelwiki.modules.identity.public import Principal

from .dto import Bookmark, EffectiveCeiling, Progress
from .ports import CatalogReadAccess, ReadingRepository


class ReadingService:
    def __init__(self, repository: ReadingRepository, catalog_access: CatalogReadAccess):
        self._repository = repository
        self._catalog_access = catalog_access

    async def get_progress(self, novel_id: int, principal: Principal) -> Progress:
        await self._catalog_access.require_readable(novel_id, principal)
        return await self._repository.get_progress(novel_id, principal.user_id)

    async def set_progress(
        self, novel_id: int, principal: Principal, chapter: float, scroll_pct: float
    ) -> None:
        await self._catalog_access.require_readable(novel_id, principal)
        if not await self._repository.chapter_exists(novel_id, chapter):
            raise NotFound("Chapter not found.")
        await self._repository.set_progress(novel_id, principal.user_id, chapter, scroll_pct)

    async def list_bookmarks(self, novel_id: int, principal: Principal) -> list[Bookmark]:
        await self._catalog_access.require_readable(novel_id, principal)
        return await self._repository.list_bookmarks(novel_id, principal.user_id)

    async def add_bookmark(
        self, novel_id: int, principal: Principal, chapter: float, note: str | None
    ) -> int:
        await self._catalog_access.require_readable(novel_id, principal)
        return await self._repository.add_bookmark(novel_id, principal.user_id, chapter, note)

    async def delete_bookmark(
        self, novel_id: int, principal: Principal, bookmark_id: int
    ) -> None:
        await self._catalog_access.require_readable(novel_id, principal)
        await self._repository.delete_bookmark(novel_id, principal.user_id, bookmark_id)

    async def effective_ceiling(
        self,
        novel_id: int,
        principal: Principal | None,
        requested_ceiling: float | None,
    ) -> EffectiveCeiling:
        novel = await self._catalog_access.require_readable(novel_id, principal)
        count, minimum, maximum = await self._repository.chapter_span(novel_id)
        if count == 0 or minimum is None or maximum is None:
            raise NotFound("No chapters found.")
        progress = None
        if principal is not None:
            progress = await self._repository.trusted_ceiling(
                novel_id, principal.user_id
            )
        trusted = progress if progress is not None else minimum
        allowed = max(minimum, min(maximum, trusted))
        requested = (
            float(requested_ceiling) if requested_ceiling is not None else None
        )
        effective = (
            allowed
            if requested is None
            else max(minimum, min(requested, allowed))
        )
        return EffectiveCeiling(
            novel=novel,
            chapter_count=count,
            min_chapter=minimum,
            max_chapter=maximum,
            requested_ceiling=requested,
            allowed_ceiling=allowed,
            effective_ceiling=effective,
            clamped=requested is not None and effective != requested,
        )
