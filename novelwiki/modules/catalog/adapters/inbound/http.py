from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from novelwiki.auth.deps import current_user
from novelwiki.kernel.errors import Forbidden, NotFound, ValidationFailed
from novelwiki.modules.identity.public import Principal

from ...application import CatalogAccessService

router = APIRouter()


class VisibilityUpdate(BaseModel):
    visibility: str


class NovelUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    description: str | None = None
    cover_url: str | None = None
    codex_enabled: bool | None = None
    shelf: str | None = None
    status_tags: list[str] | None = None
    contribution_policy: str | None = None


async def catalog_service_dependency() -> CatalogAccessService:
    raise RuntimeError("CatalogAccessService was not wired by the composition root")


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, NotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, Forbidden):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ValidationFailed):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.post("/novels/{novel_id}/library")
async def api_add_to_library(
    novel_id: int,
    user: dict = Depends(current_user),
    service: CatalogAccessService = Depends(catalog_service_dependency),
):
    """Add a readable (global/public/owned) novel to the caller's personal library."""
    try:
        await service.add_to_library(novel_id, Principal.from_user(user))
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _raise_http(exc)
    return {"status": "success"}


@router.delete("/novels/{novel_id}/library")
async def api_remove_from_library(
    novel_id: int,
    user: dict = Depends(current_user),
    service: CatalogAccessService = Depends(catalog_service_dependency),
):
    """Remove a novel from the caller's library (their progress/bookmarks are kept)."""
    await service.remove_from_library(novel_id, Principal.from_user(user))
    return {"status": "success"}


@router.patch("/novels/{novel_id}/visibility")
async def api_set_visibility(
    novel_id: int,
    payload: VisibilityUpdate,
    user: dict = Depends(current_user),
    service: CatalogAccessService = Depends(catalog_service_dependency),
):
    """Change a novel's visibility. Owner/admin only; only an admin may set/clear `global`
    (the curated shared library). Publishing to `global` reassigns ownership to the admin."""
    try:
        visibility = await service.set_visibility(
            novel_id, Principal.from_user(user), payload.visibility
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _raise_http(exc)
    return {"status": "success", "visibility": visibility}


@router.patch("/novels/{novel_id}")
async def api_update_novel(
    novel_id: int,
    payload: NovelUpdate,
    user: dict = Depends(current_user),
    service: CatalogAccessService = Depends(catalog_service_dependency),
):
    """Edit a novel. The shelf is *per-user* (stored in library_entries) and any reader may set
    it — shelving a novel also adds it to that reader's library. Status tags and base metadata
    (title, author, description, cover, codex toggle) are the novel's own data: owner/admin only.
    Other readers propose tags via the tag-suggestion endpoints instead."""
    try:
        status = await service.update_novel(
            novel_id,
            Principal.from_user(user),
            payload.model_dump(exclude_unset=True),
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _raise_http(exc)
    return {"status": status}
