from __future__ import annotations

from typing import Protocol

from .application.dto import (
    Bookmark,
    ChapterListItem,
    ChapterSnapshot,
    Contribution,
    Progress,
)


class ReadingApi(Protocol):
    async def get_progress(self, novel_id: int, user_id: int) -> Progress: ...
    async def set_progress(self, novel_id: int, user_id: int, chapter: float, scroll_pct: float) -> None: ...
    async def list_bookmarks(self, novel_id: int, user_id: int) -> list[Bookmark]: ...
    async def add_bookmark(self, novel_id: int, user_id: int, chapter: float, note: str | None) -> int: ...
    async def delete_bookmark(self, novel_id: int, user_id: int, bookmark_id: int) -> None: ...


class ReadingTransactionApi(ReadingApi, Protocol):
    async def list_chapters(self, novel_id: int) -> list[ChapterListItem]: ...
    async def get_chapter(
        self, novel_id: int, number: float, user_id: int | None
    ) -> ChapterSnapshot: ...
    async def chapter_version_and_source(
        self, novel_id: int, number: float
    ) -> tuple[int, bool]: ...
    async def update_base_content(
        self, novel_id: int, number: float, content: str,
        keep_overlay_user: int | None = None,
    ) -> int: ...
    async def save_overlay(
        self, novel_id: int, number: float, user_id: int, content: str,
        base_version: int, origin: str,
    ) -> None: ...
    async def delete_overlay(
        self, novel_id: int, number: float, user_id: int
    ) -> None: ...
    async def reanchor_overlay(
        self, novel_id: int, number: float, user_id: int, base_version: int
    ) -> None: ...
    async def get_overlay(
        self, novel_id: int, number: float, user_id: int
    ) -> tuple[str, int] | None: ...
    async def create_contribution(
        self, novel_id: int, number: float, user_id: int, content: str,
        base_version: int, status: str, auto_merged: bool,
    ) -> int: ...
    async def list_contributions(
        self, novel_id: int, status: str
    ) -> list[Contribution]: ...
    async def get_contribution(
        self, novel_id: int, contribution_id: int
    ) -> tuple[float, str, int, int, str] | None: ...
    async def mark_contribution_accepted(
        self, contribution_id: int, reviewer_id: int, content: str
    ) -> None: ...
    async def reject_contribution(
        self, novel_id: int, contribution_id: int, reviewer_id: int
    ) -> bool: ...
