from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from novelwiki.modules.catalog.public import NovelAccess


@dataclass(frozen=True)
class Progress:
    last_chapter: float | None
    max_chapter_read: float | None
    scroll_pct: float


@dataclass(frozen=True)
class Bookmark:
    id: int
    chapter: float
    note: str | None
    created_at: datetime | None


@dataclass(frozen=True)
class EffectiveCeiling:
    novel: NovelAccess
    chapter_count: int
    min_chapter: float
    max_chapter: float
    requested_ceiling: float | None
    allowed_ceiling: float
    effective_ceiling: float
    clamped: bool


@dataclass(frozen=True)
class ChapterListItem:
    number: float
    title: str | None
    language: str | None
    is_translated: bool
    translation_status: str | None
    has_content: bool
    word_count: int | None
    kind: str
    part_label: str | None


@dataclass(frozen=True)
class ChapterSnapshot:
    number: float
    title: str | None
    content: str | None
    raw_html: str | None
    content_version: int
    word_count: int | None
    has_original: bool
    language: str | None
    is_translated: bool
    translation_status: str | None
    adapter: str | None
    source_is_raw: bool
    previous_number: float | None
    previous_title: str | None
    next_number: float | None
    next_title: str | None
    next_is_raw: bool
    overlay_content: str | None
    overlay_base_version: int | None
    overlay_origin: str | None
    overlay_conflict: bool


@dataclass(frozen=True)
class ServedChapter:
    snapshot: ChapterSnapshot
    novel: NovelAccess
    content: str | None
    translation_status: str | None
    is_translated: bool
    prefetch_after: float | None


@dataclass(frozen=True)
class Contribution:
    id: int
    chapter: float
    content: str
    base_version: int
    status: str
    created_at: datetime | None
    from_user_id: int
    base_content: str | None
    current_content_version: int | None
