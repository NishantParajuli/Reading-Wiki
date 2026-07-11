from __future__ import annotations

from dataclasses import dataclass

from ..public import ChapterCeiling


@dataclass(frozen=True)
class CeilingContext:
    """Server-trusted reading boundary used by every spoiler-sensitive use case."""

    ceiling: ChapterCeiling
    requested_ceiling: float | None
    allowed_ceiling: float
    clamped: bool
    chapter_count: int
    min_chapter: float
    max_chapter: float
    novel_title: str
    novel_blurb: str
    ceiling_chapter: float | None = None
    ceiling_title: str | None = None


@dataclass(frozen=True)
class BackendDecision:
    requested: str
    resolved: str
    reason: str
    model: str | None
    policy_version: int | None
    fallback_allowed: bool


@dataclass(frozen=True)
class ActiveCodexJob:
    job_id: int
    execution_backend: str
    model: str | None


@dataclass(frozen=True)
class BuildCodex:
    force: bool = False
    from_chapter: float | None = None
    to_chapter: float | None = None
    ai_backend: str = "auto"

