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
