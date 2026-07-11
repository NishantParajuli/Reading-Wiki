"""Audiobook TTS HTTP adapter."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from novelwiki.platform.auth import current_user
from novelwiki.kernel.errors import Conflict, Forbidden, InvalidOperation, NotFound
from novelwiki.modules.identity.public import Principal
from novelwiki.modules.narration.application import (
    AudioFileGone, BookAudioCommand, ChapterAudioCommand, NarrationService,
)

router = APIRouter()


class ChapterAudioRequest(BaseModel):
    voice_id: str | None = None
    force: bool = False


class BookAudioRequest(BaseModel):
    voice_id: str | None = None
    start: float | None = None
    end: float | None = None
    count: int | None = None


async def narration_service_dependency() -> NarrationService:
    raise RuntimeError("Narration service is not configured")


async def narration_principal_factory_dependency() -> Callable[[dict], Principal]:
    raise RuntimeError("Narration principal factory is not configured")


async def _dependencies(service, principal_factory):
    if not isinstance(service, NarrationService):
        from novelwiki.bootstrap.narration import build_narration_service
        service = await build_narration_service()
    if not callable(principal_factory):
        from novelwiki.bootstrap.narration import build_narration_principal_factory
        principal_factory = build_narration_principal_factory()
    return service, principal_factory


async def _result(awaitable):
    try:
        return await awaitable
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Forbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidOperation as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AudioFileGone as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


@router.get("/tts/voices")
async def api_tts_voices(
    user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """Narrator catalog from the sidecar (empty if it's offline), plus the configured default."""
    service, _ = await _dependencies(service, principal_factory)
    return await _result(service.voices())


@router.post("/novels/{novel_id}/chapter/{number}/audio")
async def api_generate_chapter_audio(
    novel_id: int, number: float, payload: ChapterAudioRequest,
    user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """Narrate one chapter. Returns immediately with the cached audio if present (no charge),
    otherwise enqueues a job (charged per chapter in the worker as it generates)."""
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.generate_chapter(
        novel_id, number,
        ChapterAudioCommand(voice_id=payload.voice_id, force=payload.force),
        principal_factory(user),
    ))


@router.post("/novels/{novel_id}/audiobook")
async def api_generate_book_audio(
    novel_id: int, payload: BookAudioRequest, user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """Narrate a bounded, cancellable batch of a novel's prose chapters (skipping ones already
    cached for this voice). Capped at TTS_MAX_BATCH_CHAPTERS per job — narrate a long book in
    successive batches."""
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.generate_book(
        novel_id,
        BookAudioCommand(
            voice_id=payload.voice_id, start=payload.start,
            end=payload.end, count=payload.count,
        ),
        principal_factory(user),
    ))


@router.get("/novels/{novel_id}/audiobook/status")
async def api_book_audio_status(
    novel_id: int, voice_id: str | None = None, user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """Return the active whole-book narration job for this novel/voice, if any.

    This lets the UI reattach after a reload or tab close/open; the worker itself keeps
    running from the DB queue either way.
    """
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.book_status(
        novel_id, voice_id, principal_factory(user)
    ))


@router.get("/novels/{novel_id}/audio/chapters")
async def api_novel_audio_chapters(
    novel_id: int, voice_id: str | None = None, user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """The set of chapter numbers that already have shared (base) audio in the given voice —
    one cheap query that drives the TOC speaker icons. Per-user overlay audio isn't included
    (it's personal); the reader's player still resolves that correctly per chapter."""
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.audio_chapters(
        novel_id, voice_id, principal_factory(user)
    ))


@router.get("/novels/{novel_id}/audio/coverage")
async def api_novel_audio_coverage(
    novel_id: int, user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """Current shared base-audio coverage across all voices for the novel."""
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.coverage(novel_id, principal_factory(user)))


@router.get("/tts/jobs/{job_id}")
async def api_tts_job(
    job_id: int, user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.job(job_id, principal_factory(user)))


@router.post("/tts/jobs/{job_id}/cancel")
async def api_cancel_tts_job(
    job_id: int, user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.cancel_job(job_id, principal_factory(user)))


@router.get("/novels/{novel_id}/chapter/{number}/audio/status")
async def api_chapter_audio_status(
    novel_id: int, number: float, voice_id: str | None = None,
    user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """Whether this reader has playable audio for the chapter in the given voice (drives the
    player's generate-vs-play state and the TOC speaker icons)."""
    service, principal_factory = await _dependencies(service, principal_factory)
    return await _result(service.chapter_status(
        novel_id, number, voice_id, principal_factory(user)
    ))


@router.get("/novels/{novel_id}/chapter/{number}/audio.opus")
async def api_get_chapter_audio(
    novel_id: int, number: float, voice_id: str | None = None,
    user: dict = Depends(current_user),
    service: NarrationService = Depends(narration_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        narration_principal_factory_dependency
    ),
):
    """Stream a chapter's narration (Opus). Access-controlled; FileResponse handles HTTP Range
    so the player can seek. Served from AUDIO_DIR, never the public /assets mount."""
    service, principal_factory = await _dependencies(service, principal_factory)
    audio = await _result(service.chapter_audio(
        novel_id, number, voice_id, principal_factory(user)
    ))
    return FileResponse(
        audio.path, media_type=audio.media_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )
