from __future__ import annotations

from dataclasses import asdict

from fastapi import HTTPException

from novelwiki.kernel.errors import Forbidden, NotFound
from novelwiki.modules.identity.public import Principal
from novelwiki.platform.database import get_db_pool

from ...application import CatalogAccessService
from ...domain.policies import can_edit as _can_edit
from ...domain.policies import can_read as _can_read
from ...public import NovelAccess
from .postgres import PostgresCatalogRepository


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
    return novel is not None and _can_edit(_novel_access(novel), _principal(user))


async def fetch_novel(novel_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        novel = await PostgresCatalogRepository(connection).get_access(novel_id)
    if novel is None:
        return None
    result = asdict(novel)
    result["id"] = result.pop("novel_id")
    return result


async def require_readable(novel_id: int, user: dict | None) -> dict:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        try:
            novel = await CatalogAccessService(
                PostgresCatalogRepository(connection)
            ).require_readable(novel_id, _principal(user))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = asdict(novel)
    result["id"] = result.pop("novel_id")
    return result


async def require_editable(novel_id: int, user: dict | None) -> dict:
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        try:
            novel = await CatalogAccessService(
                PostgresCatalogRepository(connection)
            ).require_editable(novel_id, _principal(user))
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Forbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    result = asdict(novel)
    result["id"] = result.pop("novel_id")
    return result
