from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from novelwiki.auth.deps import current_user
from novelwiki.kernel.errors import Conflict, Forbidden, NotFound, ValidationFailed
from novelwiki.modules.acquisition.public import SourceDraft
from novelwiki.modules.catalog.public import NovelDraft
from novelwiki.modules.identity.public import Principal

from ...application import CatalogAccessService, CatalogMigrationService

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


class SourceCreate(BaseModel):
    adapter: str
    start_url: str
    language: str = "en"
    is_raw: bool = False
    chapter_offset: float = 0
    label: str | None = None
    config: dict | None = None


class NovelCreate(BaseModel):
    title: str
    author: str | None = None
    description: str | None = None
    cover_url: str | None = None
    original_language: str = "en"
    codex_enabled: bool = False
    source: SourceCreate | None = None


class TagSuggestion(BaseModel):
    tags: list[str]
    note: str | None = None


async def catalog_service_dependency() -> CatalogAccessService:
    raise RuntimeError("CatalogAccessService was not wired by the composition root")


async def catalog_migration_service_dependency() -> CatalogMigrationService:
    raise RuntimeError("CatalogMigrationService was not wired by the composition root")


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, NotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, Forbidden):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ValidationFailed):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, Conflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


async def _read_upload_file_limited(
    file: UploadFile, max_bytes: int, too_large_detail: str
) -> bytes:
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail=too_large_detail)
    return bytes(data)


@router.post("/novels")
async def api_create_novel(
    payload: NovelCreate,
    user: dict = Depends(current_user),
    service: CatalogMigrationService = Depends(catalog_migration_service_dependency),
):
    """Create a novel (owned by the caller, private by default) and optionally its first source."""
    source = SourceDraft(**payload.source.model_dump()) if payload.source else None
    try:
        novel_id, source_id = await service.create_novel(
            Principal.from_user(user),
            NovelDraft(**payload.model_dump(exclude={"source"})),
            source,
        )
    except (NotFound, Forbidden, ValidationFailed, Conflict) as exc:
        _raise_http(exc)
    return {"id": novel_id, "source_id": source_id}


@router.post("/novels/{novel_id}/cover")
async def api_upload_novel_cover(
    novel_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
    service: CatalogMigrationService = Depends(catalog_migration_service_dependency),
):
    """Upload a cover image and return an authenticated novel asset URL."""
    ext = os.path.splitext(file.filename or "")[1].lower().lstrip(".")
    mime = (file.content_type or "").lower().split(";", 1)[0].strip()
    if ext == "svg" or mime == "image/svg+xml":
        raise HTTPException(status_code=400, detail="SVG covers are not supported.")
    data = await _read_upload_file_limited(
        file, 10 * 1024 * 1024, "Cover image must be under 10 MB."
    )
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        asset = await service.store_cover(
            novel_id, Principal.from_user(user), data, file.content_type
        )
    except (NotFound, Forbidden, ValidationFailed, Conflict) as exc:
        _raise_http(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cover_url": asset["url"], "asset": asset}


@router.delete("/novels/{novel_id}")
async def api_delete_novel(
    novel_id: int,
    user: dict = Depends(current_user),
    service: CatalogMigrationService = Depends(catalog_migration_service_dependency),
):
    try:
        await service.delete_novel(novel_id, Principal.from_user(user))
    except (NotFound, Forbidden, ValidationFailed, Conflict) as exc:
        _raise_http(exc)
    return {"status": "success"}


@router.post("/novels/{novel_id}/tag-suggestions")
async def api_suggest_tags(
    novel_id: int,
    payload: TagSuggestion,
    user: dict = Depends(current_user),
    service: CatalogMigrationService = Depends(catalog_migration_service_dependency),
):
    """A reader proposes a status-tag set for a shared novel they can see but can't edit."""
    try:
        suggestion_id = await service.suggest_tags(
            novel_id, Principal.from_user(user), payload.tags, payload.note
        )
    except ValidationFailed as exc:
        # The historical endpoint deliberately uses 400 for this one policy rejection.
        if str(exc) == "You can edit this novel's tags directly.":
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _raise_http(exc)
    except (NotFound, Forbidden, Conflict) as exc:
        _raise_http(exc)
    return {"status": "pending", "id": suggestion_id}


@router.get("/novels/{novel_id}/tag-suggestions")
async def api_list_tag_suggestions(
    novel_id: int,
    status: str = "pending",
    user: dict = Depends(current_user),
    service: CatalogMigrationService = Depends(catalog_migration_service_dependency),
):
    """Owner/admin inbox of tag-suggestion proposals (defaults to pending)."""
    try:
        return await service.list_tag_suggestions(
            novel_id, Principal.from_user(user), status
        )
    except (NotFound, Forbidden, ValidationFailed, Conflict) as exc:
        _raise_http(exc)


@router.post("/novels/{novel_id}/tag-suggestions/{suggestion_id}/accept")
async def api_accept_tag_suggestion(
    novel_id: int,
    suggestion_id: int,
    user: dict = Depends(current_user),
    service: CatalogMigrationService = Depends(catalog_migration_service_dependency),
):
    """Owner/admin: apply a suggested tag set to the novel and mark the suggestion accepted."""
    try:
        tags = await service.accept_tag_suggestion(
            novel_id, suggestion_id, Principal.from_user(user)
        )
    except (NotFound, Forbidden, ValidationFailed, Conflict) as exc:
        _raise_http(exc)
    return {"status": "accepted", "tags": tags}


@router.post("/novels/{novel_id}/tag-suggestions/{suggestion_id}/reject")
async def api_reject_tag_suggestion(
    novel_id: int,
    suggestion_id: int,
    user: dict = Depends(current_user),
    service: CatalogMigrationService = Depends(catalog_migration_service_dependency),
):
    """Owner/admin: decline a tag suggestion."""
    try:
        await service.reject_tag_suggestion(
            novel_id, suggestion_id, Principal.from_user(user)
        )
    except (NotFound, Forbidden, ValidationFailed, Conflict) as exc:
        _raise_http(exc)
    return {"status": "rejected"}


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
