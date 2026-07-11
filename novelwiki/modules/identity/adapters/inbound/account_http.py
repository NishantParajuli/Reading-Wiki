from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from novelwiki.auth.deps import current_user

from novelwiki.auth.users import self_user_with_capabilities
from novelwiki.kernel.errors import Conflict, ValidationFailed
from novelwiki.platform.config import settings

from ...application import AccountService, QuotaService
from ..outbound.avatars import AvatarFilesystem
from ..principals import principal_from_user

router = APIRouter()


async def quota_service_dependency() -> QuotaService:
    raise RuntimeError("QuotaService was not wired by the composition root")


async def account_service_dependency() -> AccountService:
    raise RuntimeError("AccountService was not wired by the composition root")


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    username: str | None = None
    prefs: dict | None = None


@router.get("/me/usage")
async def api_my_usage(
    user: dict = Depends(current_user),
    service: QuotaService = Depends(quota_service_dependency),
):
    """The caller's monthly spend vs. their quota (drives the account panel)."""
    return await service.usage_and_limits(principal_from_user(user))


@router.patch("/me")
async def api_update_me(
    payload: ProfileUpdate,
    user: dict = Depends(current_user),
    service: AccountService = Depends(account_service_dependency),
):
    """Update the signed-in account's profile (display name, bio, username) and synced
    reader prefs. `prefs` is shallow-merged into the existing JSON so a partial update
    (e.g. just the reader font) doesn't clobber the rest."""
    try:
        updated = await service.update_profile(user, payload.model_dump(exclude_unset=True))
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await self_user_with_capabilities(updated)


@router.post("/me/avatar")
async def api_upload_avatar(
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
    service: AccountService = Depends(account_service_dependency),
):
    """Upload (replace) the account avatar. Stored under ASSET_DIR/_users/<id>/ and served
    by the narrowed public /assets/_users mount; the DB keeps the relative path."""
    extension = os.path.splitext(file.filename or "")[1].lower().lstrip(".")
    if (file.content_type or "").split("/")[0] != "image" and extension not in {"jpg", "jpeg", "png", "webp", "gif"}:
        raise HTTPException(status_code=400, detail="Avatar must be an image (jpg, png, webp, gif).")
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Avatar must be under 5 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    relative = AvatarFilesystem(settings.ASSET_DIR).save(int(user["id"]), bytes(data), extension or "png")
    await service.set_avatar(int(user["id"]), relative)
    return {"avatar_path": relative, "avatar_url": "/assets/" + relative}
