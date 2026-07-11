"""Shared narration coverage helpers.

These queries answer the book-level question "which current prose chapters have shared base
audio, in which voices?" without touching per-user overlay audio. Reader-specific routes still
resolve overlays separately.
"""
from __future__ import annotations

from collections.abc import Iterable


async def shared_audio_coverage(
    novel_id: int, include_voice_ids: Iterable[str] | None = None
) -> dict:
    from novelwiki.bootstrap.narration import build_narration_queries
    result = await (await build_narration_queries()).coverage(novel_id)
    existing = {row["voice_id"] for row in result["voices"]}
    for voice in sorted({
        str(value).strip() for value in (include_voice_ids or ())
        if str(value or "").strip()
    } - existing):
        result["voices"].append({
            "voice_id": voice, "have": 0,
            "missing": result["prose_chapters"], "chapters": [],
            "duration_seconds": 0, "file_bytes": 0,
        })
    result["voices"].sort(key=lambda row: row["voice_id"])
    return result
