"""Durable audiobook-narration worker + job state machine.

Mirrors the import worker (novelwiki/importer/jobs.py): narration state lives in ``tts_jobs``
and a single DB-polled background task (started from the app lifespan) advances jobs across
restarts. One GPU sidecar → one chapter generated at a time (``_TTS_LOCK``).

State machine::

    queued ──▶ generating ──▶ done            (per-chapter or a bounded book batch)
       ▲           │
       └─ (restart requeues an interrupted `generating`) ─┘
    any ──▶ failed | canceled

Generation is idempotent + resumable: a finished chapter is recorded in ``chapter_audio``
before moving on, so a restart (which requeues `generating` → `queued`) re-runs the job and
skips chapters that already have audio. Cancellation is cooperative — the worker re-reads the
job status between chapters (and between sidecar calls) and stops gracefully, keeping whatever
finished. Quota (``tts_chapters``) is charged per chapter actually generated; a cache hit or a
skipped chapter costs nothing, and exhausting quota mid-batch stops the job gracefully.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from novelwiki.config.settings import settings
from novelwiki import quota
from novelwiki.tts import tts_client, textprep
from novelwiki.tts.chapter_text import resolve_chapter_text

logger = logging.getLogger(__name__)

TRIGGER_STATUSES = ("queued",)
ACTIVE_STATUSES = ("queued", "generating")
_JSON_FIELDS = {"progress", "options"}

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
# One GPU behind the TTS sidecar → never run two narrations at once (the worker is already
# sequential, but this also guards a future standalone worker process).
_TTS_LOCK = asyncio.Lock()


async def _worker_state():
    from novelwiki.bootstrap.narration_worker import build_narration_worker_state
    return await build_narration_worker_state()


# ── Row (de)serialization ────────────────────────────────────────────────────

def _loads(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v


def _row_to_job(row) -> dict:
    job = dict(row)
    for f in _JSON_FIELDS:
        if f in job and job[f] is not None:
            job[f] = _loads(job[f])
    return job


def _numstr(number) -> str:
    try:
        f = float(number)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(number)


def chapter_target_key(novel_id: int, number, voice_id: str, version: int, user_id: int | None) -> str:
    owner = f"u{user_id}" if user_id is not None else "base"
    return f"{int(novel_id)}:{_numstr(number)}:{voice_id}:v{int(version)}:{owner}"


def chapter_dedupe_key(novel_id: int, number, voice_id: str, version: int,
                       user_id: int | None, force: bool = False) -> str:
    suffix = "force" if force else "normal"
    return f"chapter:{chapter_target_key(novel_id, number, voice_id, version, user_id)}:{suffix}"


def chapter_job_options(number, content_version: int, target_user_id: int | None,
                        force: bool = False, **extra) -> dict:
    """Canonical options for a one-chapter job.

    Target fields let routes rediscover an active job after reload. Callers add a
    dedupe key when they want rapid clicks/concurrent users to share one job.
    """
    opts = {
        "chapters": [float(number)],
        "force": bool(force),
        "target_kind": "chapter_audio",
        "target_chapter": _numstr(number),
        "target_content_version": int(content_version),
        "target_user_id": target_user_id,
    }
    opts.update(extra)
    return opts


# ── Job CRUD ─────────────────────────────────────────────────────────────────

async def create_job(novel_id: int, user_id: int | None, scope: str, voice_id: str,
                     options: dict | None = None) -> int:
    opts = dict(options or {})
    return await (await _worker_state()).create_job(
        novel_id, user_id, scope, voice_id, opts, ACTIVE_STATUSES,
    )


async def get_job(job_id: int) -> dict | None:
    row = await (await _worker_state()).get_job(job_id)
    return _row_to_job(row) if row else None


async def find_active_chapter_job(novel_id: int, number, voice_id: str, version: int,
                                  user_id: int | None, include_force: bool = True) -> dict | None:
    """Return an in-flight one-chapter job for this exact audio cache target, if any."""
    chapter = _numstr(number)
    row = await (await _worker_state()).active_chapter_job(
        active_statuses=ACTIVE_STATUSES, novel_id=novel_id, voice_id=voice_id,
        chapter=chapter, version=version, user_id=user_id,
        include_force=include_force,
    )
    return _row_to_job(row) if row else None


async def find_active_book_job(novel_id: int, voice_id: str) -> dict | None:
    """Return the active whole-book batch for a novel/voice, if one is already running."""
    row = await (await _worker_state()).active_book_job(
        novel_id, voice_id, ACTIVE_STATUSES,
    )
    return _row_to_job(row) if row else None


async def update_job(job_id: int, **fields) -> None:
    if not fields:
        return
    await (await _worker_state()).update_job(job_id, fields)


async def fail_job(job_id: int, error: str) -> None:
    logger.error(f"TTS job {job_id} failed: {error}")
    await update_job(job_id, status="failed", error=str(error)[:4000])


async def cancel_job(job_id: int) -> None:
    """Request cancellation. A queued job is never claimed; an in-flight job stops at the next
    cancellation check. Terminal jobs are left as-is."""
    await (await _worker_state()).cancel_job(job_id)


async def _is_canceled(job_id: int) -> bool:
    st = await (await _worker_state()).status(job_id)
    return st == "canceled"


async def _load_user(user_id: int | None) -> dict | None:
    return await (await _worker_state()).load_user(user_id)


# ── Audio cache (chapter_audio) ──────────────────────────────────────────────

def _audio_root() -> Path:
    return Path(settings.AUDIO_DIR)


def ensure_dirs() -> None:
    _audio_root().mkdir(parents=True, exist_ok=True)


def audio_rel(novel_id: int, number, voice_id: str, version: int, user_id: int | None) -> str:
    suffix = f"_u{user_id}" if user_id else ""
    return f"{novel_id}/{voice_id}/ch{_numstr(number)}__v{version}{suffix}.opus"


def audio_abs(rel: str) -> Path:
    return _audio_root() / rel


async def find_audio(novel_id: int, number, voice_id: str, version: int, user_id: int | None) -> dict | None:
    """Exact-match cache lookup for one (novel, chapter, voice, version, owner) audio row."""
    row = await (await _worker_state()).find_audio(
        novel_id=novel_id, number=number, voice_id=voice_id,
        version=version, user_id=user_id,
    )
    return dict(row) if row else None


async def lookup_for_reader(novel_id: int, number: float, voice_id: str, user: dict | None) -> dict | None:
    """What audio (if any) THIS reader should hear: their overlay audio if they have an overlay
    for the chapter, else the shared base audio at the current content version."""
    info = await resolve_chapter_text(novel_id, number, user)
    if info["reason"] != "ok":
        return None
    uid = user["id"] if (info["is_overlay"] and isinstance(user, dict)) else None
    return await find_audio(novel_id, number, voice_id, info["content_version"], uid)


async def _upsert_audio(novel_id, number, user_id, voice_id, language, version, rel, duration, nbytes) -> None:
    await (await _worker_state()).upsert_audio(
        novel_id=novel_id, number=number, user_id=user_id, voice_id=voice_id,
        language=language, version=version, rel=rel, duration=duration,
        nbytes=nbytes,
    )


# ── Generation ───────────────────────────────────────────────────────────────

def _target_lock(key: str):
    """Cross-process lock for one chapter-audio target."""
    return _DeferredTargetLock(key)


class _DeferredTargetLock:
    def __init__(self, key: str):
        self._key = key

    async def __aenter__(self):
        self._lock = (await _worker_state()).target_lock(self._key)
        return await self._lock.__aenter__()

    async def __aexit__(self, *args):
        return await self._lock.__aexit__(*args)


async def _generate_chapter(job: dict, user: dict, number) -> str:
    """Generate (or skip) one chapter. Returns one of:
        'cached'        already had audio (free)
        'generated'     produced new audio (charged 1 quota)
        'quota'         user is out of monthly quota → caller stops the batch
        'untranslated'  raw chapter with no translation yet → skipped
        'empty'|'missing' nothing to narrate → skipped
    """
    job_id = int(job["id"])
    novel_id = int(job["novel_id"])
    voice_id = job["voice_id"]
    opts = job.get("options") or {}
    lang_override = opts.get("language")
    force = bool(opts.get("force"))   # regenerate even if cached (the ⟳ button)

    info = await resolve_chapter_text(novel_id, number, user)
    if info["reason"] == "not_found":
        return "missing"
    if info["reason"] == "untranslated":
        return "untranslated"
    if info["reason"] != "ok" or not (info.get("text") or "").strip():
        return "empty"

    version = info["content_version"]
    uid = user["id"] if info["is_overlay"] else None

    async with _target_lock(chapter_target_key(novel_id, number, voice_id, version, uid)):
        if not force and await find_audio(novel_id, number, voice_id, version, uid):
            logger.info(f"TTS job {job_id}: chapter {_numstr(number)} already cached; skipping generation.")
            return "cached"

        # Charge quota right before the (expensive) generation, mirroring how the importer reserves
        # close to the work. A cache hit above never reaches here, so reuse stays free.
        if not await quota.try_reserve(user, "tts_chapters", 1):
            return "quota"

        paras = textprep.to_paragraphs(
            info["text"], title=info["title"], number=number, intro=settings.TTS_TITLE_INTRO,
        )
        language = lang_override or info["language"]
        logger.info(
            f"TTS job {job_id}: narrating chapter {_numstr(number)} "
            f"({len(paras)} paragraphs, voice={voice_id})."
        )
        heartbeat_stop = asyncio.Event()

        async def heartbeat():
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.wait_for(heartbeat_stop.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.info(f"TTS job {job_id}: still narrating chapter {_numstr(number)}...")

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            opus, duration = await tts_client.narrate(
                paras, voice_id, language=language,
                speed=settings.TTS_SPEED, num_step=settings.TTS_NUM_STEP,
                silence_ms=settings.TTS_PARA_SILENCE_MS, opus_bitrate=settings.TTS_OPUS_BITRATE,
            )
        finally:
            heartbeat_stop.set()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                raise
        rel = audio_rel(novel_id, number, voice_id, version, uid)
        dest = audio_abs(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Atomic publish: write a temp file then os.replace, so a force-regenerate can't corrupt
        # the audio for someone currently streaming the old version (their open fd keeps the old
        # inode), and a crash mid-write never leaves a half-written file behind the DB row.
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(opus)
        os.replace(tmp, dest)
        await _upsert_audio(novel_id, number, uid, voice_id, language, version, rel, duration, len(opus))
        logger.info(
            f"TTS job {job_id}: published chapter {_numstr(number)} "
            f"({int(duration)}s, {len(opus)} bytes)."
        )
        return "generated"


async def _run(job: dict, user: dict) -> None:
    job_id = int(job["id"])
    chapters = (job.get("options") or {}).get("chapters") or []
    total = len(chapters)
    if total == 0:
        await update_job(job_id, status="done", stage="nothing to narrate", progress={"done": 0, "total": 0})
        return

    if await _is_canceled(job_id):
        return

    if not await tts_client.sidecar_available():
        await fail_job(job_id, "TTS sidecar is unavailable. Start it with: docker compose up -d tts")
        return

    if await _is_canceled(job_id):
        return

    await update_job(job_id, status="generating", stage="narrating", error=None,
                     progress={"done": 0, "total": total})
    logger.info(f"TTS job {job_id} started: {total} chapter(s), voice={job['voice_id']}.")

    done = skipped = 0
    async with _TTS_LOCK:   # hold the GPU for this whole job
        for number in chapters:
            if await _is_canceled(job_id):
                await update_job(job_id, status="canceled", stage="canceled",
                                 progress={"done": done, "skipped": skipped, "total": total,
                                           "stopped_reason": "canceled"})
                logger.info(f"TTS job {job_id} canceled after {done}/{total} chapters.")
                return

            await update_job(job_id, progress={"done": done, "skipped": skipped, "total": total,
                                               "current_chapter": _numstr(number)})
            logger.info(f"TTS job {job_id}: processing chapter {_numstr(number)} ({done + skipped + 1}/{total}).")
            result = await _generate_chapter(job, user, number)

            if result == "quota":
                await update_job(job_id, status="done", stage="monthly TTS quota reached",
                                 progress={"done": done, "skipped": skipped, "total": total,
                                           "stopped_reason": "quota"})
                logger.info(f"TTS job {job_id} stopped on quota after {done}/{total} chapters.")
                return
            if result in ("cached", "generated"):
                done += 1
            else:
                skipped += 1   # untranslated / empty / missing

    await update_job(job_id, status="done", stage="done",
                     progress={"done": done, "skipped": skipped, "total": total})
    logger.info(f"TTS job {job_id} finished: {done} narrated/cached, {skipped} skipped of {total}.")


# ── Worker loop ──────────────────────────────────────────────────────────────

async def _requeue_interrupted() -> None:
    """A restart can kill the worker mid-job: `generating` → `queued` so it re-runs (already
    finished chapters are skipped via the chapter_audio cache)."""
    n = await (await _worker_state()).requeue_interrupted()
    if n and not n.endswith(" 0"):
        logger.info(f"Requeued interrupted TTS jobs: {n}.")


async def _claim_next() -> dict | None:
    row = await (await _worker_state()).claim_next(TRIGGER_STATUSES)
    return _row_to_job(row) if row else None


async def _process(job: dict) -> None:
    job_id = int(job["id"])
    try:
        user = await _load_user(job.get("user_id"))
        if user is None:
            await fail_job(job_id, "Job has no owner.")
            return
        if not quota.spend_allowed(user):
            await fail_job(job_id, "Verify your email to generate audiobooks.")
            return
        await _run(job, user)
    except Exception as e:
        logger.exception(f"TTS job {job_id} crashed.")
        await fail_job(job_id, f"{type(e).__name__}: {e}")


async def worker_loop(poll_interval: float = 2.0) -> None:
    ensure_dirs()
    try:
        await _requeue_interrupted()
    except Exception as e:
        logger.warning(f"TTS worker: could not requeue interrupted jobs: {e}")
    logger.info("TTS worker started.")
    while not _stop.is_set():
        try:
            job = await _claim_next()
            if job is None:
                try:
                    await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass
                continue
            await _process(job)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"TTS worker loop error: {e}")
            try:
                await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
    logger.info("TTS worker stopped.")


def start_worker() -> None:
    """Launch the background TTS worker (idempotent). Called from the FastAPI lifespan."""
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    _stop.clear()
    _worker_task = asyncio.create_task(worker_loop())


async def stop_worker() -> None:
    global _worker_task
    _stop.set()
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except (asyncio.CancelledError, Exception):
            pass
        _worker_task = None
