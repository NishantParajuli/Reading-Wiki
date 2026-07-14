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
import time
import uuid
from pathlib import Path

from novelwiki.platform.config import settings
from novelwiki.platform.observability.logging import log_context, log_event
from novelwiki.modules.narration.domain import textprep

logger = logging.getLogger(__name__)

TRIGGER_STATUSES = ("queued",)
ACTIVE_STATUSES = ("queued", "generating")
_JSON_FIELDS = {"progress", "options"}

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
# One GPU behind the TTS sidecar → never run two narrations at once (the worker is already
# sequential, but this also guards a future standalone worker process).
_TTS_LOCK = asyncio.Lock()
_runtime = None
_WORKER_ID = f"tts-{os.getpid()}-{uuid.uuid4().hex[:12]}"


def configure_worker_runtime(runtime) -> None:
    global _runtime
    _runtime = runtime


def _configured_runtime():
    if _runtime is None:
        raise RuntimeError("Narration worker runtime was not wired by the composition root")
    return _runtime


async def _worker_state():
    return await _configured_runtime().worker_state_factory()


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
    job_id = await (await _worker_state()).create_job(
        novel_id, user_id, scope, voice_id, opts, ACTIVE_STATUSES,
    )
    log_event(
        logger, logging.INFO, "tts_job.scheduled",
        f"Scheduled or reused {scope} narration job {job_id} with voice {voice_id}.",
        job_system="tts", job_id=job_id, job_kind=f"narrate_{scope}",
        novel_id=novel_id, user_id=user_id, scope=scope, voice_id=voice_id,
        chapters_total=len(opts.get("chapters") or []),
        force=bool(opts.get("force")), dedupe_key=opts.get("dedupe_key"),
    )
    return job_id


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
    if settings.LOG_JOB_PROGRESS and ({"status", "stage", "progress"} & fields.keys()):
        log_event(
            logger, logging.INFO, "tts_job.state_changed",
            f"Narration job {job_id} state changed.",
            job_system="tts", job_id=job_id, status=fields.get("status"),
            stage=fields.get("stage"), progress=fields.get("progress"),
            changed_fields=sorted(fields),
        )


async def fail_job(job_id: int, error: str) -> None:
    log_event(
        logger, logging.ERROR, "tts_job.failed",
        f"Narration job {job_id} failed.",
        job_system="tts", job_id=job_id, error=str(error)[:4000],
    )
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
    info = await _configured_runtime().resolve_chapter_text(novel_id, number, user)
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

    info = await _configured_runtime().resolve_chapter_text(novel_id, number, user)
    if info["reason"] == "not_found":
        log_event(
            logger, logging.WARNING, "tts_job.chapter_skipped",
            f"Narration job {job_id} skipped missing chapter {_numstr(number)}.",
            chapter=_numstr(number), skip_reason="missing",
        )
        return "missing"
    if info["reason"] == "untranslated":
        log_event(
            logger, logging.WARNING, "tts_job.chapter_skipped",
            f"Narration job {job_id} skipped untranslated chapter {_numstr(number)}.",
            chapter=_numstr(number), skip_reason="untranslated",
        )
        return "untranslated"
    if info["reason"] != "ok" or not (info.get("text") or "").strip():
        log_event(
            logger, logging.WARNING, "tts_job.chapter_skipped",
            f"Narration job {job_id} skipped empty chapter {_numstr(number)}.",
            chapter=_numstr(number), skip_reason=info.get("reason") or "empty",
        )
        return "empty"

    version = info["content_version"]
    uid = user["id"] if info["is_overlay"] else None

    async with _target_lock(chapter_target_key(novel_id, number, voice_id, version, uid)):
        if not force and await find_audio(novel_id, number, voice_id, version, uid):
            log_event(
                logger, logging.INFO, "tts_job.chapter_cached",
                f"Narration job {job_id} reused cached audio for chapter {_numstr(number)}.",
                chapter=_numstr(number), voice_id=voice_id,
                content_version=version, target_user_id=uid,
            )
            return "cached"

        # Charge quota right before the (expensive) generation, mirroring how the importer reserves
        # close to the work. A cache hit above never reaches here, so reuse stays free.
        if not await _configured_runtime().quota.try_reserve(user, "tts_chapters", 1):
            log_event(
                logger, logging.WARNING, "tts_job.quota_exhausted",
                f"Narration job {job_id} reached TTS quota before chapter {_numstr(number)}.",
                chapter=_numstr(number), quota_kind="tts_chapters",
            )
            return "quota"

        paras = textprep.to_paragraphs(
            info["text"], title=info["title"], number=number, intro=settings.TTS_TITLE_INTRO,
        )
        language = lang_override or info["language"]
        generation_started = time.monotonic()
        log_event(
            logger, logging.INFO, "tts_job.chapter_started",
            f"Narration job {job_id} started chapter {_numstr(number)} with voice {voice_id}.",
            chapter=_numstr(number), paragraphs=len(paras), voice_id=voice_id,
            language=language, content_version=version, target_user_id=uid,
            force=force, tts_steps=settings.TTS_NUM_STEP, speed=settings.TTS_SPEED,
        )
        heartbeat_stop = asyncio.Event()

        async def heartbeat():
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.wait_for(heartbeat_stop.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    log_event(
                        logger, logging.INFO, "tts_job.chapter_heartbeat",
                        f"Narration job {job_id} is still generating chapter {_numstr(number)}.",
                        chapter=_numstr(number),
                        elapsed_ms=round((time.monotonic() - generation_started) * 1000, 2),
                    )

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            opus, duration = await _configured_runtime().tts_client.narrate(
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
        log_event(
            logger, logging.INFO, "tts_job.chapter_completed",
            f"Narration job {job_id} published chapter {_numstr(number)} audio.",
            chapter=_numstr(number), duration_seconds=int(duration),
            audio_bytes=len(opus), voice_id=voice_id, language=language,
            content_version=version, target_user_id=uid,
            duration_ms=round((time.monotonic() - generation_started) * 1000, 2),
        )
        return "generated"


class _NarrationWorkerOperations:
    load_user = staticmethod(_load_user)
    spend_allowed = staticmethod(lambda user: _configured_runtime().quota.spend_allowed(user))
    is_canceled = staticmethod(_is_canceled)
    sidecar_available = staticmethod(lambda: _configured_runtime().tts_client.sidecar_available())
    generate_chapter = staticmethod(_generate_chapter)
    update_job = staticmethod(update_job)
    fail_job = staticmethod(fail_job)
    chapter_label = staticmethod(_numstr)

    @staticmethod
    def info(message):
        log_event(logger, logging.INFO, "tts_job.lifecycle", message)

    @staticmethod
    def exception(message):
        log_event(
            logger, logging.ERROR, "tts_job.crashed", message, exc_info=True
        )

    @staticmethod
    async def acquire_generation():
        return _TTS_LOCK


async def _run(job: dict, user: dict) -> None:
    """Stable test seam; orchestration is owned by the application service."""
    from novelwiki.modules.narration.application.worker import NarrationWorkerService
    await NarrationWorkerService(_NarrationWorkerOperations())._run(job, user)


# ── Worker loop ──────────────────────────────────────────────────────────────

async def _requeue_interrupted() -> None:
    """A restart can kill the worker mid-job: `generating` → `queued` so it re-runs (already
    finished chapters are skipped via the chapter_audio cache)."""
    n = await (await _worker_state()).requeue_interrupted()
    if n and not n.endswith(" 0"):
        log_event(
            logger, logging.WARNING, "tts_job.interrupted_requeued",
            "Requeued narration jobs interrupted by a prior process exit.",
            job_system="tts", worker_type="tts", worker_id=_WORKER_ID,
            requeued_jobs=int(n.rsplit(" ", 1)[-1]),
        )


async def _claim_next() -> dict | None:
    row = await (await _worker_state()).claim_next(TRIGGER_STATUSES)
    return _row_to_job(row) if row else None


async def _process(job: dict) -> None:
    from novelwiki.modules.narration.application.worker import NarrationWorkerService
    job_id = int(job["id"])
    options = job.get("options") or {}
    with log_context(
        worker_type="tts", worker_id=_WORKER_ID, job_system="tts",
        job_id=job_id, job_kind=f"narrate_{job.get('scope', 'unknown')}",
        novel_id=job.get("novel_id"), user_id=job.get("user_id"),
        scope=job.get("scope"), voice_id=job.get("voice_id"),
    ):
        started = time.monotonic()
        log_event(
            logger, logging.INFO, "tts_job.started",
            f"Starting {job.get('scope', 'unknown')} narration job {job_id} "
            f"with voice {job.get('voice_id')}.",
            status=job.get("status"), stage=job.get("stage"),
            chapters_total=len(options.get("chapters") or []),
            force=bool(options.get("force")),
        )
        try:
            await NarrationWorkerService(_NarrationWorkerOperations()).process(job)
        finally:
            try:
                finished = await get_job(job_id)
            except Exception:
                log_event(
                    logger, logging.WARNING, "tts_job.outcome_lookup_failed",
                    f"Could not load the final state for narration job {job_id}.",
                    exc_info=True,
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
            else:
                status = (finished or {}).get("status", "missing")
                level = logging.ERROR if status == "failed" else (
                    logging.WARNING if status == "canceled" else logging.INFO
                )
                log_event(
                    logger, level, "tts_job.attempt_finished",
                    f"Finished narration job {job_id} with status {status}.",
                    status=status, stage=(finished or {}).get("stage"),
                    progress=(finished or {}).get("progress"),
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )


async def worker_loop(poll_interval: float = 2.0) -> None:
    ensure_dirs()
    try:
        await _requeue_interrupted()
    except Exception as e:
        log_event(
            logger, logging.WARNING, "worker.maintenance_failed",
            "Narration worker could not requeue interrupted jobs.", exc_info=True,
            worker_type="tts", worker_id=_WORKER_ID, job_system="tts",
        )
    log_event(
        logger, logging.INFO, "worker.started", "Narration worker started.",
        worker_type="tts", worker_id=_WORKER_ID, job_system="tts",
        poll_interval_seconds=poll_interval,
    )
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
        except Exception:
            log_event(
                logger, logging.ERROR, "worker.loop_failed",
                "Narration worker loop failed.", exc_info=True,
                worker_type="tts", worker_id=_WORKER_ID, job_system="tts",
            )
            try:
                await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
    log_event(
        logger, logging.INFO, "worker.stopped", "Narration worker stopped.",
        worker_type="tts", worker_id=_WORKER_ID, job_system="tts",
    )


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
