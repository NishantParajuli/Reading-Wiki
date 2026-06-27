"""Centralized novel access control. One place decides who can read/edit a novel.

Visibility tiers: private (owner only) · public (any logged-in user) · global
(admin-curated shared library). `user` may be None for unauthenticated callers.
"""
from fastapi import HTTPException

from novelwiki.db.connection import get_db_pool


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
            "SELECT id, owner_id, visibility, contribution_policy, title FROM novels WHERE id = $1;",
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
