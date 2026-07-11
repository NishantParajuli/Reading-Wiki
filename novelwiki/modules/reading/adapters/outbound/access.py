from __future__ import annotations

from dataclasses import asdict, dataclass

from fastapi import HTTPException

from novelwiki.kernel.errors import NotFound
from novelwiki.modules.catalog.public import catalog_access_service
from novelwiki.modules.identity.public import Principal
from novelwiki.platform.database import get_db_pool

from ...application import ReadingService
from .postgres import PostgresReadingRepository


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


async def require_effective_ceiling(
    novel_id: int, user: dict | None, requested_ceiling: float | None
) -> CodexCeiling:
    principal = Principal.from_user(user) if isinstance(user, dict) else None
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        try:
            result = await ReadingService(
                PostgresReadingRepository(connection),
                catalog_access_service(connection),
            ).effective_ceiling(novel_id, principal, requested_ceiling)
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
