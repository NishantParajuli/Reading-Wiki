from __future__ import annotations

from typing import Protocol

from novelwiki.modules.identity.public import Principal

from .dto import ChapterListItem, ChapterSnapshot, Contribution, Bookmark, Progress


class CatalogReadAccess(Protocol):
    async def require_readable(
        self, novel_id: int, principal: Principal | None
    ) -> object: ...


class SourceMetadataPort(Protocol):
    async def source_metadata(self, source_id: int | None) -> dict: ...


class ReadingRepository(Protocol):
    async def get_progress(self, novel_id: int, user_id: int) -> Progress: ...
    async def chapter_exists(self, novel_id: int, chapter: float) -> bool: ...
    async def set_progress(self, novel_id: int, user_id: int, chapter: float, scroll_pct: float) -> None: ...
    async def list_bookmarks(self, novel_id: int, user_id: int) -> list[Bookmark]: ...
    async def add_bookmark(self, novel_id: int, user_id: int, chapter: float, note: str | None) -> int: ...
    async def delete_bookmark(self, novel_id: int, user_id: int, bookmark_id: int) -> None: ...
    async def chapter_span(self, novel_id: int) -> tuple[int, float | None, float | None]: ...
    async def trusted_ceiling(self, novel_id: int, user_id: int) -> float | None: ...


class ChapterTranslationPort(Protocol):
    async def translate_chapter(
        self, novel_id: int, number: float, principal: Principal | None
    ) -> dict: ...

    async def translate_raw_chapter(
        self, novel_id: int, number: float
    ) -> str | None: ...

    async def prefetch(
        self, novel_id: int, after_number: float, count: int,
        principal: Principal | None,
    ) -> None: ...


class SelfTranslationQuotaPort(Protocol):
    async def check_and_reserve(
        self, principal: Principal, kind: str, units: int = 1
    ) -> None: ...
