from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChapterAudioCommand:
    voice_id: str | None = None
    force: bool = False


@dataclass(frozen=True)
class BookAudioCommand:
    voice_id: str | None = None
    start: float | None = None
    end: float | None = None
    count: int | None = None


@dataclass(frozen=True)
class AudioFile:
    path: str
    media_type: str = "audio/ogg"

