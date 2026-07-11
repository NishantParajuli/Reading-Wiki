from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from novelwiki.auth.deps import current_user
from novelwiki.kernel.errors import (
    Conflict, Forbidden, NotFound, ProviderUnavailable, QuotaExceeded,
    ValidationFailed,
)
from novelwiki.modules.identity.public import Principal

from ...application import BuildCodex, CodexMigrationService

logger = logging.getLogger(__name__)
router = APIRouter()


class AskRequest(BaseModel):
    question: str
    ceiling: float


class CodexBuild(BaseModel):
    force: bool = False
    from_chapter: float | None = None
    to_chapter: float | None = None
    ai_backend: Literal["auto", "api", "agy"] = "auto"


class MergePayload(BaseModel):
    keep_id: int
    drop_id: int


class Citation(BaseModel):
    kind: str
    id: int
    chapter: float
    snippet: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    evidence_ids: dict
    requested_ceiling: float | None = None
    allowed_ceiling: float | None = None
    effective_ceiling: float | None = None
    ceiling_clamped: bool = False


async def codex_migration_service_dependency() -> CodexMigrationService:
    raise RuntimeError("CodexMigrationService was not wired by the composition root")


async def codex_principal_factory_dependency() -> Callable[[dict], Principal]:
    raise RuntimeError("Codex principal factory was not wired by the composition root")


def _expected_http(exc: Exception) -> None:
    status = (
        404 if isinstance(exc, NotFound) else
        403 if isinstance(exc, Forbidden) else
        409 if isinstance(exc, Conflict) else
        429 if isinstance(exc, QuotaExceeded) else
        503 if isinstance(exc, ProviderUnavailable) else 422
    )
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _principal(factory: Callable[[dict], Principal], user: dict) -> Principal:
    return factory(user)


@router.get("/novels/{novel_id}/meta")
async def api_meta_chapters(
    novel_id: int, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    """Chapter span + display title/blurb so the codex ceiling control can be bounded."""
    try:
        return await service.queries.meta(
            novel_id, _principal(principal_factory, user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _expected_http(exc)


@router.get("/novels/{novel_id}/stats")
async def api_meta_stats(
    novel_id: int, ceiling: float, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    """Spoiler-safe aggregate stats for the codex home surface (all bounded by ceiling)."""
    try:
        return await service.queries.stats(
            novel_id, ceiling, _principal(principal_factory, user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _expected_http(exc)


@router.get("/novels/{novel_id}/entities")
async def api_list_entities(
    novel_id: int, ceiling: float, type: str | None = None,
    q: str | None = None, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    try:
        return await service.queries.list_entities(
            novel_id, ceiling, _principal(principal_factory, user), type, q
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Error listing entities: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/entity/resolve")
async def api_resolve_entity(
    novel_id: int, name: str, ceiling: float, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    try:
        return await service.queries.resolve_entity(
            novel_id, name, ceiling, _principal(principal_factory, user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Error resolving entity: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/entity/{entity_id}")
async def api_get_entity_profile(
    novel_id: int, entity_id: int, ceiling: float,
    user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    """Structured profile at the ceiling, using the wiki_cache fast path."""
    try:
        return await service.queries.entity_profile(
            novel_id, entity_id, ceiling, _principal(principal_factory, user)
        )
    except (NotFound, Forbidden, QuotaExceeded, ValidationFailed) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Error fetching profile: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/entity/{entity_id}/relationships")
async def api_get_relationships(
    novel_id: int, entity_id: int, ceiling: float,
    other_id: int | None = None, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    try:
        return await service.queries.relationships(
            novel_id, entity_id, ceiling, _principal(principal_factory, user), other_id
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Error fetching relationships: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/entity/{entity_id}/timeline")
async def api_get_timeline(
    novel_id: int, entity_id: int, ceiling: float,
    user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    try:
        return await service.queries.timeline(
            novel_id, entity_id, ceiling, _principal(principal_factory, user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Error fetching timeline: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/entity/{entity_id}/identities")
async def api_get_identities(
    novel_id: int, entity_id: int, ceiling: float,
    user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    try:
        return await service.queries.identities(
            novel_id, entity_id, ceiling, _principal(principal_factory, user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Error fetching identity links: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/ask", response_model=AskResponse)
async def ask_question(
    novel_id: int, req: AskRequest, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    """Agentic spoiler-safe Q&A scoped to one novel.

    A cached answer (same normalized question + effective ceiling) is served cheaply and
    bypasses every cost gate. An uncached question fans out to embeddings, rerank, and
    several model calls, so it must clear the read-side AI cost controls first: a length
    cap (checked before any provider call), a verified-email spend gate, a per-user hourly
    cap on uncached asks, and a small concurrency ceiling."""
    try:
        return await service.queries.ask(
            novel_id, req.question, req.ceiling, _principal(principal_factory, user)
        )
    except (NotFound, Forbidden, QuotaExceeded, ValidationFailed) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Agentic Q&A error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="The AI service failed to answer. Please try again.",
        ) from exc


@router.post("/novels/{novel_id}/codex/build")
async def api_codex_build(
    novel_id: int, payload: CodexBuild, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    """Schedule a durable codex build (chunk → embed → extract → rebuild BM25) that survives
    restarts. Repeated clicks for the same range dedupe onto the active job so the expensive
    build runs once, and the reserved codex-build quota is refunded if the job ultimately fails
    or is cancelled (the durable worker finalizes it)."""
    try:
        return await service.commands.schedule_build(
            novel_id, _principal(principal_factory, user),
            BuildCodex(**payload.model_dump()),
        )
    except (
        NotFound, Forbidden, Conflict, QuotaExceeded,
        ProviderUnavailable, ValidationFailed,
    ) as exc:
        _expected_http(exc)


@router.post("/novels/{novel_id}/merge-entities")
async def trigger_merge(
    novel_id: int, payload: MergePayload, user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    try:
        return await service.commands.merge_entities(
            novel_id, payload.keep_id, payload.drop_id,
            _principal(principal_factory, user),
        )
    except (NotFound, Forbidden) as exc:
        _expected_http(exc)
    except Exception as exc:
        logger.error("Error merging entities: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


__all__ = [
    "router", "codex_migration_service_dependency",
    "codex_principal_factory_dependency",
]
