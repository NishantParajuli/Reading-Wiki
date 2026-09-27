from __future__ import annotations
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from novelwiki.platform.auth import current_user
from novelwiki.modules.identity.public import Principal
from novelwiki.kernel.errors import (
    ApplicationError,
    Conflict,
    Forbidden,
    InvalidOperation,
    NotFound,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
)

router = APIRouter()


async def illustration_service_dependency():
    raise RuntimeError("Illustration service was not wired")


class GenerateIllustrations(BaseModel):
    count: int | None = Field(default=None, ge=1, le=3)
    style: Literal["luminous", "painterly"] = "luminous"
    force: bool = False


class GenerateIllustrationRange(BaseModel):
    from_chapter: float = Field(ge=0, allow_inf_nan=False)
    to_chapter: float = Field(ge=0, allow_inf_nan=False)
    style: Literal["luminous", "painterly"] = "luminous"
    force: bool = False


def translate_error(exc):
    status = (
        404
        if isinstance(exc, NotFound)
        else 403
        if isinstance(exc, Forbidden)
        else 409
        if isinstance(exc, Conflict)
        else 503
        if isinstance(exc, ProviderUnavailable)
        else 429
        if isinstance(exc, (RateLimited, QuotaExceeded))
        else 400
        if isinstance(exc, InvalidOperation)
        else 422
    )
    headers = (
        {"Retry-After": str(exc.retry_after)}
        if isinstance(exc, RateLimited) and exc.retry_after is not None
        else None
    )
    raise HTTPException(status_code=status, detail=str(exc), headers=headers) from exc


@router.get("/novels/{novel_id}/chapters/{chapter}/illustrations")
async def illustrations(
    novel_id: int,
    chapter: float,
    user=Depends(current_user),
    service=Depends(illustration_service_dependency),
):
    try:
        return await service.list(novel_id, chapter, Principal.from_user(user))
    except ApplicationError as exc:
        translate_error(exc)


@router.post("/novels/{novel_id}/chapters/{chapter}/illustrations")
async def generate_illustrations(
    novel_id: int,
    chapter: float,
    payload: GenerateIllustrations,
    user=Depends(current_user),
    service=Depends(illustration_service_dependency),
):
    try:
        return await service.generate(
            novel_id, chapter, Principal.from_user(user), **payload.model_dump()
        )
    except ApplicationError as exc:
        translate_error(exc)


@router.get(
    "/novels/{novel_id}/illustrations/{art_id}/image",
    response_class=Response,
    responses={
        200: {
            "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}
        }
    },
)
async def illustration_image(
    novel_id: int,
    art_id: UUID,
    user=Depends(current_user),
    service=Depends(illustration_service_dependency),
):
    try:
        content = await service.image(novel_id, art_id, Principal.from_user(user))
        return Response(
            content,
            media_type="image/png",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except ApplicationError as exc:
        translate_error(exc)


@router.get("/novels/{novel_id}/illustrations")
async def illustration_range_info(
    novel_id: int,
    user=Depends(current_user),
    service=Depends(illustration_service_dependency),
):
    try:
        return await service.range_info(novel_id, Principal.from_user(user))
    except ApplicationError as exc:
        translate_error(exc)


@router.post("/novels/{novel_id}/illustrations")
async def generate_illustration_range(
    novel_id: int,
    payload: GenerateIllustrationRange,
    user=Depends(current_user),
    service=Depends(illustration_service_dependency),
):
    try:
        return await service.generate_range(
            novel_id, Principal.from_user(user), **payload.model_dump()
        )
    except ApplicationError as exc:
        translate_error(exc)
