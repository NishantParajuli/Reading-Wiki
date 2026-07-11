from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from novelwiki.platform.auth import current_user
from collections.abc import Callable
from typing import Literal

from novelwiki.kernel.errors import (
    Conflict, Forbidden, NotFound, ProviderUnavailable, QuotaExceeded, ValidationFailed,
)
from novelwiki.modules.identity.public import Principal

from ...application import GlossaryService, ScheduleTranslation, TranslationSchedulingService

router = APIRouter()


class GlossaryUpsert(BaseModel):
    source_term: str
    translation: str
    term_type: str | None = None
    notes: str | None = None
    locked: bool = False


class TranslateTrigger(BaseModel):
    from_chapter: float | None = None
    to_chapter: float | None = None
    force: bool = False
    seed_from_codex: bool = False
    ai_backend: Literal["auto", "api", "agy"] = "auto"


async def glossary_service_dependency() -> GlossaryService:
    raise RuntimeError("GlossaryService was not wired by the composition root")


async def translation_scheduling_service_dependency() -> TranslationSchedulingService:
    raise RuntimeError("TranslationSchedulingService was not wired by the composition root")


async def principal_factory_dependency() -> Callable[[dict], Principal]:
    raise RuntimeError("Identity principal factory was not wired by the composition root")


def _raise_http(exc: Exception) -> None:
    status = (
        404 if isinstance(exc, NotFound) else
        403 if isinstance(exc, Forbidden) else
        409 if isinstance(exc, Conflict) else
        429 if isinstance(exc, QuotaExceeded) else
        503 if isinstance(exc, ProviderUnavailable) else 422
    )
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/translate")
async def api_translate(
    novel_id: int, payload: TranslateTrigger, user: dict = Depends(current_user),
    service: TranslationSchedulingService = Depends(translation_scheduling_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(principal_factory_dependency),
):
    """Schedule a durable translation batch over a chapter range (manual batch; reading itself
    uses on-demand + prefetch). The worker computes the pending chapters at execution time,
    meters each against the caller's monthly quota as it translates, and stops gracefully on
    quota exhaustion. Optionally seeds the glossary from the codex first."""
    try:
        return await service.schedule(
            novel_id,
            principal_factory(user),
            ScheduleTranslation(**payload.model_dump()),
        )
    except (NotFound, Forbidden, Conflict, QuotaExceeded, ProviderUnavailable, ValidationFailed) as exc:
        _raise_http(exc)


@router.post("/novels/{novel_id}/glossary/seed")
async def api_seed_glossary(
    novel_id: int, user: dict = Depends(current_user),
    service: GlossaryService = Depends(glossary_service_dependency),
):
    """Seed the glossary's English spellings from the established codex entities."""
    try:
        seeded = await service.seed(novel_id, Principal.from_user(user))
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    return {"status": "success", "seeded": seeded}


@router.get("/novels/{novel_id}/glossary")
async def api_list_glossary(
    novel_id: int, user: dict = Depends(current_user),
    service: GlossaryService = Depends(glossary_service_dependency),
):
    try:
        rows = await service.list(novel_id, Principal.from_user(user))
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    return [
        {"id": row.id, "source_term": row.source_term, "translation": row.translation,
         "term_type": row.term_type, "notes": row.notes, "locked": row.locked}
        for row in rows
    ]


@router.put("/novels/{novel_id}/glossary")
async def api_upsert_glossary(
    novel_id: int, payload: GlossaryUpsert, user: dict = Depends(current_user),
    service: GlossaryService = Depends(glossary_service_dependency),
):
    """Add or update a glossary term (manual edits win and are typically locked)."""
    try:
        term_id = await service.upsert(
            novel_id, Principal.from_user(user), **payload.model_dump()
        )
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    return {"id": term_id}


@router.delete("/novels/{novel_id}/glossary/{term_id}")
async def api_delete_glossary(
    novel_id: int, term_id: int, user: dict = Depends(current_user),
    service: GlossaryService = Depends(glossary_service_dependency),
):
    try:
        await service.delete(novel_id, term_id, Principal.from_user(user))
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    return {"status": "success"}
