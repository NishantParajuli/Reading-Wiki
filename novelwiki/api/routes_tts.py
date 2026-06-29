"""Audiobook TTS API: voices, per-chapter + whole-book narration jobs, status, cancel, and
the access-controlled audio stream.

Generation is durable + cached: enqueuing returns a job the worker advances on the GPU
sidecar; finished chapters are cached in ``chapter_audio`` and reused by every reader (a
per-user overlay gets its own audio). Audio is served only through this authed route (never
the public /assets mount) so private-novel narration stays private.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.deps import current_user
from novelwiki.auth.access import require_readable, is_admin
from novelwiki import quota
from novelwiki.tts import tts_client
from novelwiki.tts import worker as tts_worker
from novelwiki.tts.chapter_text import resolve_chapter_text

logger = logging.getLogger(__name__)
router = APIRouter()


class ChapterAudioRequest(BaseModel):
    voice_id: str | None = None
    force: bool = False


class BookAudioRequest(BaseModel):
    voice_id: str | None = None
    start: float | None = None      # first chapter to narrate (default: from the beginning)
    count: int | None = None        # how many missing chapters (clamped to TTS_MAX_BATCH_CHAPTERS)


def _voice_or_default(voice_id: str | None) -> str:
    return (voice_id or settings.TTS_DEFAULT_VOICE or "").strip()


def _job_view(job: dict) -> dict:
    return {
        "id": int(job["id"]),
        "novel_id": int(job["novel_id"]),
        "scope": job["scope"],
        "voice_id": job["voice_id"],
        "status": job["status"],
        "stage": job.get("stage"),
        "progress": job.get("progress") or {},
        "error": job.get("error"),
    }


@router.get("/tts/voices")
async def api_tts_voices(user: dict = Depends(current_user)):
    """Narrator catalog from the sidecar (empty if it's offline), plus the configured default."""
    return {
        "voices": await tts_client.list_voices(),
        "default": settings.TTS_DEFAULT_VOICE,
        "enabled": settings.TTS_ENABLED,
    }


@router.post("/novels/{novel_id}/chapter/{number}/audio")
async def api_generate_chapter_audio(novel_id: int, number: float, payload: ChapterAudioRequest,
                                     user: dict = Depends(current_user)):
    """Narrate one chapter. Returns immediately with the cached audio if present (no charge),
    otherwise enqueues a job (charged per chapter in the worker as it generates)."""
    await require_readable(novel_id, user)
    voice = _voice_or_default(payload.voice_id)
    if not voice:
        raise HTTPException(status_code=400, detail="No voice selected.")

    info = await resolve_chapter_text(novel_id, number, user)
    if info["reason"] == "not_found":
        raise HTTPException(status_code=404, detail="Chapter not found.")
    if info["reason"] == "untranslated":
        raise HTTPException(status_code=409, detail="Translate this chapter before narrating it.")
    if info["reason"] != "ok":
        raise HTTPException(status_code=409, detail="This chapter has no readable text to narrate.")

    if not payload.force:
        uid = user["id"] if info["is_overlay"] else None
        cached = await tts_worker.find_audio(novel_id, number, voice, info["content_version"], uid)
        if cached:
            return {"status": "ready", "cached": True,
                    "duration": cached.get("duration_seconds"), "voice_id": voice}

    # Preflight only (zero-remaining / unverified → 429). The actual unit is charged in the worker.
    await quota.check_available(user, "tts_chapters", 1)
    job_id = await tts_worker.create_job(
        novel_id, user["id"], "chapter", voice,
        options={"chapters": [float(number)], "force": bool(payload.force)},
    )
    return {"status": "queued", "cached": False, "job_id": job_id, "voice_id": voice}


@router.post("/novels/{novel_id}/audiobook")
async def api_generate_book_audio(novel_id: int, payload: BookAudioRequest,
                                  user: dict = Depends(current_user)):
    """Narrate a bounded, cancellable batch of a novel's prose chapters (skipping ones already
    cached for this voice). Capped at TTS_MAX_BATCH_CHAPTERS per job — narrate a long book in
    successive batches."""
    await require_readable(novel_id, user)
    voice = _voice_or_default(payload.voice_id)
    if not voice:
        raise HTTPException(status_code=400, detail="No voice selected.")

    cap = settings.TTS_MAX_BATCH_CHAPTERS
    want = cap if not payload.count or payload.count <= 0 else min(int(payload.count), cap)
    start = payload.start if payload.start is not None else None

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.number, (a.id IS NOT NULL) AS has_audio
            FROM chapters c
            LEFT JOIN chapter_audio a
              ON a.novel_id = c.novel_id AND a.chapter = c.number AND a.voice_id = $3
                 AND a.content_version = c.content_version AND a.user_id IS NULL
            WHERE c.novel_id = $1
              AND (c.kind IS NULL OR c.kind = 'chapter')
              AND ($2::numeric IS NULL OR c.number >= $2)
            ORDER BY c.number ASC;
            """,
            novel_id, start, voice,
        )
    if not rows:
        raise HTTPException(status_code=404, detail="This novel has no chapters to narrate.")

    already_cached = sum(1 for r in rows if r["has_audio"])
    missing = [float(r["number"]) for r in rows if not r["has_audio"]]
    capped = len(missing) > want
    selected = missing[:want]
    if not selected:
        return {"status": "ready", "total": 0, "already_cached": already_cached, "capped": False,
                "message": "Every selected chapter is already narrated in this voice."}

    await quota.check_available(user, "tts_chapters", 1)   # gate unverified / zero-remaining
    job_id = await tts_worker.create_job(
        novel_id, user["id"], "book", voice, options={"chapters": selected},
    )
    return {"status": "queued", "job_id": job_id, "total": len(selected),
            "already_cached": already_cached, "capped": capped, "voice_id": voice}


@router.get("/novels/{novel_id}/audio/chapters")
async def api_novel_audio_chapters(novel_id: int, voice_id: str | None = None,
                                   user: dict = Depends(current_user)):
    """The set of chapter numbers that already have shared (base) audio in the given voice —
    one cheap query that drives the TOC speaker icons. Per-user overlay audio isn't included
    (it's personal); the reader's player still resolves that correctly per chapter."""
    await require_readable(novel_id, user)
    voice = _voice_or_default(voice_id)
    if not voice:
        return {"voice_id": voice, "chapters": []}
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT chapter FROM chapter_audio "
            "WHERE novel_id = $1 AND voice_id = $2 AND user_id IS NULL ORDER BY chapter;",
            novel_id, voice,
        )
    return {"voice_id": voice, "chapters": [float(r["chapter"]) for r in rows]}


@router.get("/tts/jobs/{job_id}")
async def api_tts_job(job_id: int, user: dict = Depends(current_user)):
    job = await tts_worker.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("user_id") not in (None, user["id"]) and not is_admin(user):
        raise HTTPException(status_code=404, detail="Job not found.")
    return _job_view(job)


@router.post("/tts/jobs/{job_id}/cancel")
async def api_cancel_tts_job(job_id: int, user: dict = Depends(current_user)):
    job = await tts_worker.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("user_id") != user["id"] and not is_admin(user):
        raise HTTPException(status_code=403, detail="You can't cancel this job.")
    await tts_worker.cancel_job(job_id)
    return _job_view(await tts_worker.get_job(job_id))


@router.get("/novels/{novel_id}/chapter/{number}/audio/status")
async def api_chapter_audio_status(novel_id: int, number: float, voice_id: str | None = None,
                                   user: dict = Depends(current_user)):
    """Whether this reader has playable audio for the chapter in the given voice (drives the
    player's generate-vs-play state and the TOC speaker icons)."""
    await require_readable(novel_id, user)
    voice = _voice_or_default(voice_id)
    row = await tts_worker.lookup_for_reader(novel_id, number, voice, user) if voice else None
    return {"cached": bool(row), "voice_id": voice,
            "duration": row.get("duration_seconds") if row else None}


@router.get("/novels/{novel_id}/chapter/{number}/audio.opus")
async def api_get_chapter_audio(novel_id: int, number: float, voice_id: str | None = None,
                                user: dict = Depends(current_user)):
    """Stream a chapter's narration (Opus). Access-controlled; FileResponse handles HTTP Range
    so the player can seek. Served from AUDIO_DIR, never the public /assets mount."""
    await require_readable(novel_id, user)
    voice = _voice_or_default(voice_id)
    row = await tts_worker.lookup_for_reader(novel_id, number, voice, user) if voice else None
    if not row:
        raise HTTPException(status_code=404, detail="No audio for this chapter/voice yet.")
    path = tts_worker.audio_abs(row["audio_path"])
    if not os.path.exists(path):
        raise HTTPException(status_code=410, detail="Audio file missing (regenerate it).")
    return FileResponse(path, media_type="audio/ogg",
                        headers={"Cache-Control": "private, max-age=86400"})
