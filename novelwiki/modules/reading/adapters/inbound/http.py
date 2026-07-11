from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from novelwiki.auth.deps import current_user
from novelwiki.kernel.errors import Forbidden, NotFound
from novelwiki.modules.identity.public import Principal

from ...application.services import ReadingService

router = APIRouter()


class ProgressUpdate(BaseModel):
    last_chapter: float
    scroll_pct: float = 0


class BookmarkCreate(BaseModel):
    chapter: float
    note: str | None = None


async def reading_service_dependency() -> ReadingService:
    raise RuntimeError("ReadingService was not wired by the composition root")


def _principal(user: dict) -> Principal:
    return Principal.from_user(user)


def _translate_access_error(exc: Exception) -> None:
    if isinstance(exc, NotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, Forbidden):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


@router.get("/novels/{novel_id}/progress")
async def api_get_progress(
    novel_id: int,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        progress = await service.get_progress(novel_id, _principal(user))
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {
        "last_chapter": progress.last_chapter,
        "max_chapter_read": progress.max_chapter_read,
        "scroll_pct": progress.scroll_pct,
    }


@router.put("/novels/{novel_id}/progress")
async def api_set_progress(
    novel_id: int,
    payload: ProgressUpdate,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        await service.set_progress(
            novel_id, _principal(user), payload.last_chapter, payload.scroll_pct
        )
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {"status": "success"}


@router.get("/novels/{novel_id}/bookmarks")
async def api_list_bookmarks(
    novel_id: int,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        rows = await service.list_bookmarks(novel_id, _principal(user))
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return [
        {
            "id": row.id,
            "chapter": row.chapter,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.post("/novels/{novel_id}/bookmarks")
async def api_add_bookmark(
    novel_id: int,
    payload: BookmarkCreate,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        bookmark_id = await service.add_bookmark(
            novel_id, _principal(user), payload.chapter, payload.note
        )
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {"id": bookmark_id}


@router.delete("/novels/{novel_id}/bookmarks/{bookmark_id}")
async def api_delete_bookmark(
    novel_id: int,
    bookmark_id: int,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        await service.delete_bookmark(novel_id, _principal(user), bookmark_id)
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {"status": "success"}
