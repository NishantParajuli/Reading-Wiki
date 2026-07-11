"""Resolve the final readable text of a chapter for narration.

Mirrors the reader endpoint's text resolution (novelwiki/api/routes.py ``api_get_chapter``):
the base ``chapters.content`` plus a per-user ``chapter_overlays`` override if present. Unlike
the reader, this does NOT translate on demand — narration operates on text that already
exists, so a raw, untranslated chapter is reported as ``untranslated`` (the caller surfaces
"translate this chapter first") rather than silently spending translation quota.

The ``is_overlay`` flag tells the cache layer whether the audio is per-user (an edited
translation) or shared base audio.
"""
from __future__ import annotations


async def resolve_chapter_text(novel_id: int, number: float, user: dict | None) -> dict:
    from novelwiki.bootstrap.reading_migration import build_reading_narration_gateway
    return await (await build_reading_narration_gateway()).resolve_narration_text(
        novel_id, number, int(user["id"]) if isinstance(user, dict) else None
    )
