from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChapterCeiling:
    value: float


class CodexArtifacts(Protocol):
    async def has_chapter_artifacts(self, novel_id: int, chapters: tuple[float, ...]) -> bool: ...
    async def invalidate_chapter_range(self, novel_id: int, start: float, end: float) -> None: ...
