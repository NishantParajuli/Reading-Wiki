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
from pathlib import Path

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki import quota
from novelwiki.tts import tts_client, textprep
from novelwiki.tts.chapter_text import resolve_chapter_text

logger = logging.getLogger(__name__)

TRIGGER_STATUSES = ("queued",)
_JSON_FIELDS = {"progress", "options"}

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
# One GPU behind the TTS sidecar → never run two narrations at once (the worker is already
# sequential, but this also guards a future standalone worker process).
_TTS_LOCK = asyncio.Lock()


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


# ── Job CRUD ─────────────────────────────────────────────────────────────────

async def create_job(novel_id: int, user_id: int | None, scope: str, voice_id: str,
                     options: dict | None = None) -> int:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            """
            INSERT INTO tts_jobs (novel_id, user_id, scope, voice_id, options, status, stage)
            VALUES ($1, $2, $3, $4, $5, 'queued', 'queued') RETURNING id;
            """,
            novel_id, user_id, scope, voice_id, json.dumps(options or {}),
        ))


async def get_job(job_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tts_jobs WHERE id = $1;", job_id)
    return _row_to_job(row) if row else None


async def update_job(job_id: int, **fields) -> None:
    if not fields:
        return
    sets, args = [], []
    for k, v in fields.items():
        args.append(json.dumps(v) if k in _JSON_FIELDS and v is not None else v)
        sets.append(f"{k} = ${len(args)}")
    args.append(job_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE tts_jobs SET {', '.join(sets)}, updated_at = now() WHERE id = ${len(args)};",
            *args,
        )


async def fail_job(job_id: int, error: str) -> None:
    logger.error(f"TTS job {job_id} failed: {error}")
    await update_job(job_id, status="failed", error=str(error)[:4000])


async def cancel_job(job_id: int) -> None:
    """Request cancellation. A queued job is never claimed; an in-flight job stops at the next
    cancellation check. Terminal jobs are left as-is."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tts_jobs SET status='canceled', stage='canceled', updated_at=now() "
            "WHERE id = $1 AND status IN ('queued','generating');",
            job_id,
        )


async def _is_canceled(job_id: int) -> bool:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        st = await conn.fetchval("SELECT status FROM tts_jobs WHERE id = $1;", job_id)
    return st == "canceled"


async def _load_user(user_id: int | None) -> dict | None:
    if user_id is None:
        return None
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1;", user_id)
    return dict(row) if row else None


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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        if user_id is None:
            row = await conn.fetchrow(
                "SELECT * FROM chapter_audio WHERE novel_id=$1 AND chapter=$2 AND voice_id=$3 "
                "AND content_version=$4 AND user_id IS NULL;",
                novel_id, number, voice_id, version,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM chapter_audio WHERE novel_id=$1 AND chapter=$2 AND voice_id=$3 "
                "AND content_version=$4 AND user_id=$5;",
                novel_id, number, voice_id, version, user_id,
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # ON CONFLICT targets the matching partial unique index (base vs per-user).
        if user_id is None:
            await conn.execute(
                """
                INSERT INTO chapter_audio
                  (novel_id, chapter, user_id, voice_id, language, content_version, audio_path, duration_seconds, file_bytes)
                VALUES ($1,$2,NULL,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (novel_id, chapter, voice_id, content_version) WHERE user_id IS NULL
                DO UPDATE SET audio_path=EXCLUDED.audio_path, duration_seconds=EXCLUDED.duration_seconds,
                              file_bytes=EXCLUDED.file_bytes, language=EXCLUDED.language, created_at=now();
                """,
                novel_id, number, voice_id, language, version, rel, int(duration), int(nbytes),
            )
        else:
            await conn.execute(
                """
                INSERT INTO chapter_audio
                  (novel_id, chapter, user_id, voice_id, language, content_version, audio_path, duration_seconds, file_bytes)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (novel_id, chapter, voice_id, content_version, user_id) WHERE user_id IS NOT NULL
                DO UPDATE SET audio_path=EXCLUDED.audio_path, duration_seconds=EXCLUDED.duration_seconds,
                              file_bytes=EXCLUDED.file_bytes, language=EXCLUDED.language, created_at=now();
                """,
                novel_id, number, user_id, voice_id, language, version, rel, int(duration), int(nbytes),
            )


# ── Generation ───────────────────────────────────────────────────────────────

async def _generate_chapter(job: dict, user: dict, number) -> str:
    """Generate (or skip) one chapter. Returns one of:
        'cached'        already had audio (free)
        'generated'     produced new audio (charged 1 quota)
        'quota'         user is out of monthly quota → caller stops the batch
        'untranslated'  raw chapter with no translation yet → skipped
        'empty'|'missing' nothing to narrate → skipped
    """
    novel_id = int(job["novel_id"])
    voice_id = job["voice_id"]
    lang_override = (job.get("options") or {}).get("language")

    info = await resolve_chapter_text(novel_id, number, user)
    if info["reason"] == "not_found":
        return "missing"
    if info["reason"] == "untranslated":
        return "untranslated"
    if info["reason"] != "ok" or not (info.get("text") or "").strip():
        return "empty"

    version = info["content_version"]
    uid = user["id"] if info["is_overlay"] else None

    if await find_audio(novel_id, number, voice_id, version, uid):
        return "cached"

    # Charge quota right before the (expensive) generation, mirroring how the importer reserves
    # close to the work. A cache hit above never reaches here, so reuse stays free.
    if not await quota.try_reserve(user, "tts_chapters", 1):
        return "quota"

    paras = textprep.to_paragraphs(
        info["text"], title=info["title"], number=number, intro=settings.TTS_TITLE_INTRO,
    )
    language = lang_override or info["language"]
    opus, duration = await tts_client.narrate(
        paras, voice_id, language=language,
        speed=settings.TTS_SPEED, num_step=settings.TTS_NUM_STEP,
        silence_ms=settings.TTS_PARA_SILENCE_MS, opus_bitrate=settings.TTS_OPUS_BITRATE,
    )
    rel = audio_rel(novel_id, number, voice_id, version, uid)
    dest = audio_abs(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(opus)
    await _upsert_audio(novel_id, number, uid, voice_id, language, version, rel, duration, len(opus))
    return "generated"


async def _run(job: dict, user: dict) -> None:
    job_id = int(job["id"])
    chapters = (job.get("options") or {}).get("chapters") or []
    total = len(chapters)
    if total == 0:
        await update_job(job_id, status="done", stage="nothing to narrate", progress={"done": 0, "total": 0})
        return

    if not await tts_client.sidecar_available():
        await fail_job(job_id, "TTS sidecar is unavailable. Start it with: docker compose up -d tts")
        return

    await update_job(job_id, status="generating", stage="narrating", error=None,
                     progress={"done": 0, "total": total})

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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        n = await conn.execute(
            "UPDATE tts_jobs SET status='queued', stage='requeued after restart' WHERE status='generating';"
        )
    if n and not n.endswith(" 0"):
        logger.info(f"Requeued interrupted TTS jobs: {n}.")


async def _claim_next() -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM tts_jobs WHERE status = ANY($1::text[]) ORDER BY updated_at ASC LIMIT 1;",
            list(TRIGGER_STATUSES),
        )
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
