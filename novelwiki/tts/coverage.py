"""Shared narration coverage helpers.

These queries answer the book-level question "which current prose chapters have shared base
audio, in which voices?" without touching per-user overlay audio. Reader-specific routes still
resolve overlays separately.
"""
from __future__ import annotations

from collections.abc import Iterable

from novelwiki.db.connection import get_db_pool


def _num(v) -> float:
    return float(v)


async def shared_audio_coverage(novel_id: int, include_voice_ids: Iterable[str] | None = None) -> dict:
    """Return current-version, shared-base audio coverage for one novel.

    Only rows with ``user_id IS NULL`` are counted, and an audio row is current only when its
    ``content_version`` matches the chapter row it belongs to.
    """
    include = [str(v).strip() for v in (include_voice_ids or []) if str(v or "").strip()]
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        prose_rows = await conn.fetch(
            """
            SELECT number
            FROM chapters
            WHERE novel_id = $1 AND (kind IS NULL OR kind = 'chapter')
            ORDER BY number ASC;
            """,
            novel_id,
        )
        audio_rows = await conn.fetch(
            """
            SELECT c.number AS chapter, a.voice_id, a.duration_seconds, a.file_bytes
            FROM chapters c
            JOIN chapter_audio a
              ON a.novel_id = c.novel_id
             AND a.chapter = c.number
             AND a.content_version = c.content_version
             AND a.user_id IS NULL
            WHERE c.novel_id = $1
              AND (c.kind IS NULL OR c.kind = 'chapter')
            ORDER BY c.number ASC, a.voice_id ASC;
            """,
            novel_id,
        )

    prose_count = len(prose_rows)
    by_chapter: dict[float, set[str]] = {}
    by_voice: dict[str, dict] = {}

    for vid in include:
        by_voice.setdefault(vid, {"voice_id": vid, "chapters": set(), "duration_seconds": 0, "file_bytes": 0})

    for row in audio_rows:
        ch = _num(row["chapter"])
        vid = str(row["voice_id"])
        by_chapter.setdefault(ch, set()).add(vid)
        rec = by_voice.setdefault(vid, {"voice_id": vid, "chapters": set(), "duration_seconds": 0, "file_bytes": 0})
        rec["chapters"].add(ch)
        rec["duration_seconds"] += int(row["duration_seconds"] or 0)
        rec["file_bytes"] += int(row["file_bytes"] or 0)

    voices = []
    for vid in sorted(by_voice):
        rec = by_voice[vid]
        chapters = sorted(rec["chapters"])
        have = len(chapters)
        voices.append({
            "voice_id": vid,
            "have": have,
            "missing": max(0, prose_count - have),
            "chapters": chapters,
            "duration_seconds": rec["duration_seconds"],
            "file_bytes": rec["file_bytes"],
        })

    chapters = [
        {"chapter": ch, "voices": sorted(voices)}
        for ch, voices in sorted(by_chapter.items(), key=lambda kv: kv[0])
    ]
    any_count = len(by_chapter)

    return {
        "prose_chapters": prose_count,
        "chapters_with_any_audio": any_count,
        "have": any_count,
        "missing_any": max(0, prose_count - any_count),
        "missing": max(0, prose_count - any_count),
        "voices": voices,
        "chapters": chapters,
    }
