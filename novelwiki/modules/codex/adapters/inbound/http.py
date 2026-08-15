from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from novelwiki.platform.auth import current_user
from novelwiki.kernel.errors import (
    Conflict, Forbidden, NotFound, ProviderUnavailable, QuotaExceeded,
    ValidationFailed,
)
from novelwiki.modules.identity.public import Principal

from ...application import BuildCodex, CodexMigrationService

logger = logging.getLogger(__name__)
router = APIRouter()

_CODEX_STREAM_MEDIA_TYPE = "application/x-ndjson"
_CODEX_HEARTBEAT_SECONDS = 15.0


class AskRequest(BaseModel):
    question: str
    ceiling: float


class CodexBuild(BaseModel):
    force: bool = False
    from_chapter: float | None = None
    to_chapter: float | None = None
    ai_backend: Literal["auto", "api", "agy", "openai_codex"] = "auto"


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


def _expected_status(exc: Exception) -> int:
    return (
        404 if isinstance(exc, NotFound) else
        403 if isinstance(exc, Forbidden) else
        409 if isinstance(exc, Conflict) else
        429 if isinstance(exc, QuotaExceeded) else
        503 if isinstance(exc, ProviderUnavailable) else 422
    )


def _expected_http(exc: Exception) -> None:
    raise HTTPException(status_code=_expected_status(exc), detail=str(exc)) from exc


def _principal(factory: Callable[[dict], Principal], user: dict) -> Principal:
    return factory(user)


def _stream_frame(event: str, **payload) -> str:
    return json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n"


async def _stream_codex_result(
    operation: Callable[[], Awaitable[dict]],
    *,
    failure_detail: str,
    heartbeat_seconds: float = _CODEX_HEARTBEAT_SECONDS,
):
    """Keep an expensive Codex read alive while preserving cancellation and safe errors."""
    task = asyncio.create_task(operation())
    try:
        # Commit response bytes immediately, before the first provider call can exceed a
        # reverse proxy's read timeout.
        yield _stream_frame("started")
        while True:
            done, _ = await asyncio.wait({task}, timeout=heartbeat_seconds)
            if task not in done:
                yield _stream_frame("heartbeat")
                continue
            if task.cancelled():
                yield _stream_frame(
                    "error", detail="Codex generation was canceled.", status=499
                )
                return
            try:
                result = task.result()
            except (
                NotFound, Forbidden, Conflict, QuotaExceeded,
                ProviderUnavailable, ValidationFailed,
            ) as exc:
                yield _stream_frame(
                    "error", detail=str(exc), status=_expected_status(exc)
                )
            except Exception:
                logger.exception("Streamed Codex read failed")
                yield _stream_frame("error", detail=failure_detail, status=502)
            else:
                yield _stream_frame("result", data=result)
            return
    finally:
        # A closed browser connection must release the read-side concurrency slot and stop
        # any provider work still owned by this request.
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def _streaming_response(stream) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type=_CODEX_STREAM_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


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
    """Ceiling-bounded knowledge stats plus non-story completed-build coverage."""
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


@router.get(
    "/novels/{novel_id}/entity/{entity_id}",
    responses={
        200: {
            "description": (
                "A JSON entity profile, or newline-delimited keepalive events followed "
                "by the profile when application/x-ndjson is requested."
            ),
            "content": {
                _CODEX_STREAM_MEDIA_TYPE: {"schema": {"type": "string"}},
            },
        }
    },
)
async def api_get_entity_profile(
    novel_id: int, entity_id: int, ceiling: float, request: Request = None,
    user: dict = Depends(current_user),
    service: CodexMigrationService = Depends(codex_migration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(codex_principal_factory_dependency),
):
    """Structured profile at the ceiling, using the wiki_cache fast path."""
    try:
        principal = _principal(principal_factory, user)
        if (
            request is not None
            and _CODEX_STREAM_MEDIA_TYPE in request.headers.get("accept", "").lower()
        ):
            return _streaming_response(_stream_codex_result(
                lambda: service.queries.entity_profile(
                    novel_id, entity_id, ceiling, principal
                ),
                failure_detail="The AI service failed to build this Codex entry. Please try again.",
            ))
        return await service.queries.entity_profile(
            novel_id, entity_id, ceiling, principal
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


@router.post(
    "/novels/{novel_id}/ask",
    response_model=AskResponse,
    responses={
        200: {
            "description": (
                "A JSON answer, or newline-delimited keepalive events followed by the "
                "answer when application/x-ndjson is requested."
            ),
            "content": {
                _CODEX_STREAM_MEDIA_TYPE: {"schema": {"type": "string"}},
            },
        }
    },
)
async def ask_question(
    novel_id: int, req: AskRequest, request: Request = None,
    user: dict = Depends(current_user),
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
        principal = _principal(principal_factory, user)
        if (
            request is not None
            and _CODEX_STREAM_MEDIA_TYPE in request.headers.get("accept", "").lower()
        ):
            return _streaming_response(_stream_codex_result(
                lambda: service.queries.ask(
                    novel_id, req.question, req.ceiling, principal
                ),
                failure_detail="The AI service failed to answer. Please try again.",
            ))
        return await service.queries.ask(
            novel_id, req.question, req.ceiling, principal
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
