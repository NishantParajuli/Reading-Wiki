"""Stable compatibility access helpers backed by module application services."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from fastapi import HTTPException

from novelwiki.kernel.errors import Forbidden, NotFound
from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
from novelwiki.modules.catalog.application import CatalogAccessService
from novelwiki.modules.catalog.domain.policies import can_edit as _can_edit
from novelwiki.modules.catalog.domain.policies import can_read as _can_read
from novelwiki.modules.catalog.public import NovelAccess
from novelwiki.modules.identity.public import Principal
from novelwiki.modules.reading.adapters.outbound.postgres import PostgresReadingRepository
from novelwiki.modules.reading.application import ReadingService
from novelwiki.platform.database import get_db_pool


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


def _principal(user: dict | None) -> Principal | None:
    return Principal.from_user(user) if isinstance(user, dict) else None


def _novel_access(novel: dict) -> NovelAccess:
    return NovelAccess(
        novel_id=int(novel.get("novel_id", novel.get("id"))),
        owner_id=int(novel["owner_id"]) if novel.get("owner_id") is not None else None,
        visibility=novel.get("visibility") or "private",
        contribution_policy=novel.get("contribution_policy"),
        title=novel.get("title"), description=novel.get("description"),
    )


def is_admin(user: dict | None) -> bool:
    return isinstance(user, dict) and Principal.from_user(user).is_admin


def can_read(novel: dict, user: dict | None) -> bool:
    return novel is not None and _can_read(_novel_access(novel), _principal(user))


def can_edit(novel: dict, user: dict | None) -> bool:
    return novel is not None and _can_edit(_novel_access(novel), _principal(user))


async def fetch_novel(novel_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        novel = await PostgresCatalogRepository(connection).get_access(novel_id)
    if novel is None:
        return None
    result = asdict(novel); result["id"] = result.pop("novel_id")
    return result


async def _require(novel_id: int, user: dict | None, editable: bool) -> dict:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        service = CatalogAccessService(PostgresCatalogRepository(connection))
        try:
            novel = await (
                service.require_editable(novel_id, _principal(user))
                if editable else service.require_readable(novel_id, _principal(user))
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Forbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    result = asdict(novel); result["id"] = result.pop("novel_id")
    return result


async def require_readable(novel_id: int, user: dict | None) -> dict:
    return await _require(novel_id, user, False)


async def require_editable(novel_id: int, user: dict | None) -> dict:
    return await _require(novel_id, user, True)


async def require_effective_ceiling(
    novel_id: int, user: dict | None, requested_ceiling: float | None
) -> CodexCeiling:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        try:
            result = await ReadingService(
                PostgresReadingRepository(connection),
                CatalogAccessService(PostgresCatalogRepository(connection)),
            ).effective_ceiling(novel_id, _principal(user), requested_ceiling)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    novel = asdict(result.novel); novel["id"] = novel.pop("novel_id")
    return CodexCeiling(
        novel=novel, chapter_count=result.chapter_count,
        min_chapter=result.min_chapter, max_chapter=result.max_chapter,
        requested_ceiling=result.requested_ceiling,
        allowed_ceiling=result.allowed_ceiling,
        effective_ceiling=result.effective_ceiling, clamped=result.clamped,
    )


__all__ = [
    "CodexCeiling", "can_edit", "can_read", "fetch_novel", "is_admin",
    "require_editable", "require_effective_ceiling", "require_readable",
]
