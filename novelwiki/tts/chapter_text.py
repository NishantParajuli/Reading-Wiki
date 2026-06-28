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

from novelwiki.db.connection import get_db_pool


async def resolve_chapter_text(novel_id: int, number: float, user: dict | None) -> dict:
    """Returns a dict with:
        reason: 'ok' | 'not_found' | 'empty' | 'untranslated'
        text: final readable prose (None unless reason == 'ok')
        title, language, content_version: chapter metadata
        is_overlay: True if `text` is this user's overlay (→ per-user audio cache)
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.number, c.title, c.content, c.content_version, c.language,
                   (c.original_text IS NOT NULL) AS has_original, c.kind
            FROM chapters c WHERE c.novel_id = $1 AND c.number = $2;
            """,
            novel_id, number,
        )
        if not row:
            return {"reason": "not_found", "text": None}
        overlay = None
        if isinstance(user, dict):
            overlay = await conn.fetchrow(
                "SELECT content FROM chapter_overlays WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
                user["id"], novel_id, number,
            )

    base = {
        "title": row["title"],
        "language": row["language"],
        "content_version": int(row["content_version"] or 1),
        "kind": row["kind"] or "chapter",
        "is_overlay": False,
        "text": None,
    }

    if overlay and (overlay["content"] or "").strip():
        return {**base, "reason": "ok", "text": overlay["content"], "is_overlay": True}

    content = row["content"]
    if content and content.strip():
        return {**base, "reason": "ok", "text": content}
    # No readable content. Distinguish a raw chapter awaiting translation from a truly empty one.
    if row["has_original"]:
        return {**base, "reason": "untranslated"}
    return {**base, "reason": "empty"}
