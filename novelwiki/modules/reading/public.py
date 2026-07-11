from __future__ import annotations

from typing import Any, Protocol

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
    async def source_chapter_numbers(self, source_id: int) -> tuple[float, ...]: ...
    async def renumber_source_chapters(
        self, source_id: int, novel_id: int, delta: float
    ) -> int: ...
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


class ReadingTranslationTransactionApi(Protocol):
    async def commit_translation(
        self, novel_id: int, chapter: float, *, expected_source_hash: str,
        expected_content_version: int, translated_title: str | None,
        translation: str, model_label: str, run_id: Any | None,
    ) -> dict: ...


class ReadingTranslationApi(Protocol):
    async def stage_translation_batch(
        self, novel_id: int, chapters: list[float], run_id: Any, force: bool
    ) -> list[dict]: ...
    async def reset_staged_translations(self, run_id: Any, status: str) -> int: ...
    async def translation_candidate(self, novel_id: int, chapter: float) -> dict | None: ...
    async def mark_translation_started(
        self, novel_id: int, chapter: float, source_hash: str
    ) -> None: ...
    async def mark_translation_failed(
        self, novel_id: int, chapter: float, only_unowned: bool = False
    ) -> None: ...
    async def pending_after(
        self, novel_id: int, after: float, count: int
    ) -> list[float]: ...
    async def translation_range(
        self, novel_id: int, start: float | None, end: float | None, force: bool
    ) -> list[float]: ...
    async def agy_pending(
        self, novel_id: int, start: float | None, end: float | None, force: bool
    ) -> list[float]: ...
    async def source_lengths(
        self, novel_id: int, chapters: list[float]
    ) -> dict[float, int]: ...


class ReadingIngestionApi(Protocol):
    async def resume_url(self, source_id: int) -> str | None: ...
    async def upsert_ingested_chapter(
        self, source: dict, number: float, chapter: object, force: bool,
        *, kind: str = "chapter", part_label: str | None = None,
        minimum_content_version: int | None = None,
    ) -> bool: ...


class ReadingIngestionTransactionApi(ReadingIngestionApi, Protocol):
    async def source_versions(self, source_id: int) -> dict[float, int]: ...
    async def delete_source_chapters(self, source_id: int) -> None: ...
    async def mark_overlay_conflicts(
        self, novel_id: int, chapters: tuple[float, ...]
    ) -> None: ...
    async def other_source_numbers(
        self, novel_id: int, source_id: int
    ) -> set[float]: ...
    async def preserve_content_version(
        self, novel_id: int, chapter: float, minimum: int
    ) -> int: ...


class ReadingNarrationApi(Protocol):
    async def resolve_narration_text(
        self, novel_id: int, chapter: float, user_id: int | None
    ) -> dict: ...
    async def prose_chapters(
        self, novel_id: int, start: float | None = None, end: float | None = None
    ) -> list[dict]: ...


class ReadingCodexApi(Protocol):
    async def chapter_snapshot(self, novel_id: int, chapter: float) -> dict | None: ...
    async def chapter_numbers(
        self, novel_id: int, start: float | None = None, end: float | None = None,
        require_content: bool = False,
    ) -> list[float]: ...
    async def chapter_at_or_before(
        self, novel_id: int, ceiling: float
    ) -> dict | None: ...


class ReadingCodexTransactionApi(Protocol):
    async def locked_chapter_snapshot(
        self, novel_id: int, chapter: float
    ) -> dict | None: ...


async def require_effective_ceiling(
    novel_id: int, user: dict | None, requested_ceiling: float | None
):
    from .adapters.outbound.access import require_effective_ceiling as implementation

    return await implementation(novel_id, user, requested_ceiling)
