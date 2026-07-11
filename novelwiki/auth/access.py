"""Centralized novel access control. One place decides who can read/edit a novel.

Visibility tiers: private (owner only) · public (any logged-in user) · global
(admin-curated shared library). `user` may be None for unauthenticated callers.
"""
from dataclasses import dataclass
from dataclasses import asdict

from fastapi import HTTPException

from novelwiki.db.connection import get_db_pool
from novelwiki.kernel.errors import Forbidden, NotFound
from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
from novelwiki.modules.catalog.application import CatalogAccessService
from novelwiki.modules.catalog.domain.policies import can_edit as _can_edit
from novelwiki.modules.catalog.domain.policies import can_read as _can_read
from novelwiki.modules.catalog.public import NovelAccess
from novelwiki.modules.identity.public import Principal


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
    return isinstance(user, dict) and Principal.from_user(user).is_admin


def _principal(user: dict | None) -> Principal | None:
    return Principal.from_user(user) if isinstance(user, dict) else None


def _novel_access(novel: dict) -> NovelAccess:
    return NovelAccess(
        novel_id=int(novel.get("novel_id", novel.get("id"))),
        owner_id=int(novel["owner_id"]) if novel.get("owner_id") is not None else None,
        visibility=novel.get("visibility") or "private",
        contribution_policy=novel.get("contribution_policy"),
        title=novel.get("title"),
        description=novel.get("description"),
    )


def can_read(novel: dict, user: dict | None) -> bool:
    return novel is not None and _can_read(_novel_access(novel), _principal(user))


def can_edit(novel: dict, user: dict | None) -> bool:
    """Edit base content/metadata/sources. Owner or admin only."""
    return novel is not None and _can_edit(_novel_access(novel), _principal(user))


async def fetch_novel(novel_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        novel = await PostgresCatalogRepository(conn).get_access(novel_id)
    if novel is None:
        return None
    result = asdict(novel)
    result["id"] = result.pop("novel_id")
    return result


async def require_readable(novel_id: int, user: dict | None) -> dict:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            novel = await CatalogAccessService(
                PostgresCatalogRepository(conn)
            ).require_readable(novel_id, _principal(user))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = asdict(novel)
    result["id"] = result.pop("novel_id")
    return result


async def require_editable(novel_id: int, user: dict | None) -> dict:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            novel = await CatalogAccessService(
                PostgresCatalogRepository(conn)
            ).require_editable(novel_id, _principal(user))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Forbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    result = asdict(novel)
    result["id"] = result.pop("novel_id")
    return result


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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        from novelwiki.modules.reading.adapters.outbound.postgres import (
            PostgresReadingRepository,
        )
        from novelwiki.modules.reading.application import ReadingService

        try:
            result = await ReadingService(
                PostgresReadingRepository(conn),
                CatalogAccessService(PostgresCatalogRepository(conn)),
            ).effective_ceiling(
                novel_id,
                _principal(user),
                requested_ceiling,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    novel = asdict(result.novel)
    novel["id"] = novel.pop("novel_id")

    return CodexCeiling(
        novel=novel,
        chapter_count=result.chapter_count,
        min_chapter=result.min_chapter,
        max_chapter=result.max_chapter,
        requested_ceiling=result.requested_ceiling,
        allowed_ceiling=result.allowed_ceiling,
        effective_ceiling=result.effective_ceiling,
        clamped=result.clamped,
    )
