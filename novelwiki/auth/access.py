"""Centralized novel access control. One place decides who can read/edit a novel.

Visibility tiers: private (owner only) · public (any logged-in user) · global
(admin-curated shared library). `user` may be None for unauthenticated callers.
"""
from dataclasses import dataclass

from fastapi import HTTPException

from novelwiki.db.connection import get_db_pool


@dataclass(frozen=True)
class CodexCeiling:
    novel: dict
    chapter_count: int
    min_chapter: float
    max_chapter: float
    requested_ceiling: float | None
    allowed_ceiling: float
    effective_ceiling: float
    clamped: bool


def is_admin(user: dict | None) -> bool:
    return isinstance(user, dict) and user.get("role") == "admin"


def can_read(novel: dict, user: dict | None) -> bool:
    if novel is None:
        return False
    if novel.get("visibility") in ("global", "public"):
        return True
    if isinstance(user, dict) and (novel.get("owner_id") == user["id"] or is_admin(user)):
        return True
    return False


def can_edit(novel: dict, user: dict | None) -> bool:
    """Edit base content/metadata/sources. Owner or admin only."""
    if novel is None or not isinstance(user, dict):
        return False
    return novel.get("owner_id") == user["id"] or is_admin(user)


async def fetch_novel(novel_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, owner_id, visibility, contribution_policy, title, description FROM novels WHERE id = $1;",
            novel_id,
        )
    return dict(row) if row else None


async def require_readable(novel_id: int, user: dict | None) -> dict:
    novel = await fetch_novel(novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found.")
    if not can_read(novel, user):
        # 404 (not 403) so we don't leak the existence of private novels.
        raise HTTPException(status_code=404, detail="Novel not found.")
    return novel


async def require_editable(novel_id: int, user: dict | None) -> dict:
    novel = await fetch_novel(novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="Novel not found.")
    if not can_read(novel, user):
        raise HTTPException(status_code=404, detail="Novel not found.")
    if not can_edit(novel, user):
        raise HTTPException(status_code=403, detail="You don't have permission to edit this novel.")
    return novel


async def require_effective_ceiling(
    novel_id: int,
    user: dict | None,
    requested_ceiling: float | None,
) -> CodexCeiling:
    """Resolve the trusted codex ceiling for this reader.

    Codex requests may ask for a lower ceiling, but they may not raise the boundary
    above the highest chapter the server has actually served to this user. With no
    trusted progress yet, the first chapter is visible.
    """
    novel = await require_readable(novel_id, user)
    user_id = user.get("id") if isinstance(user, dict) else None
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        span = await conn.fetchrow(
            "SELECT COUNT(*) AS count, MIN(number) AS min_chapter, MAX(number) AS max_chapter "
            "FROM chapters WHERE novel_id = $1;",
            novel_id,
        )
        progress_ceiling = None
        if user_id is not None:
            progress_ceiling = await conn.fetchval(
                """
                SELECT max_chapter_read
                FROM reading_progress
                WHERE novel_id = $1 AND user_id = $2;
                """,
                novel_id, user_id,
            )

    chapter_count = int(span["count"] or 0) if span else 0
    if chapter_count == 0 or span["min_chapter"] is None or span["max_chapter"] is None:
        raise HTTPException(status_code=404, detail="No chapters found.")

    min_chapter = float(span["min_chapter"])
    max_chapter = float(span["max_chapter"])
    trusted = float(progress_ceiling) if progress_ceiling is not None else min_chapter
    allowed = max(min_chapter, min(max_chapter, trusted))

    requested = float(requested_ceiling) if requested_ceiling is not None else None
    effective = allowed if requested is None else max(min_chapter, min(requested, allowed))
    clamped = requested is not None and effective != requested

    return CodexCeiling(
        novel=novel,
        chapter_count=chapter_count,
        min_chapter=min_chapter,
        max_chapter=max_chapter,
        requested_ceiling=requested,
        allowed_ceiling=allowed,
        effective_ceiling=effective,
        clamped=clamped,
    )
