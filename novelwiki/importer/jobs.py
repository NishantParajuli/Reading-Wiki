"""Durable import-job state machine + the worker that drives it.

A deploy here is an image rebuild, which kills any in-process work, and OCR can span
days under the Gemini free-tier quota — so import state lives in ``import_jobs`` and a
single DB-polled worker (started from the app lifespan) advances jobs across restarts.

State machine (S1 path; OCR states land in S3)::

    uploaded ──parse──▶ parsing ──▶ awaiting_review ──commit──▶ committing ──▶ committed
       ▲                                                                          │
       └────────── (restart requeues an interrupted `parsing`) ───────────────────
    any ──▶ failed | canceled

The worker only ever processes ONE job at a time (a single sequential asyncio loop), so
there is no in-process race; ``parsing`` is an in-progress marker requeued on restart,
while ``committing`` is left as-is and simply re-run (commit is idempotent).
"""
from __future__ import annotations

import asyncio
import json
import logging

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.importer import storage

logger = logging.getLogger(__name__)

# Statuses the worker actively advances (trigger states). `parsing`/`ocr_running`/
# `committing` are in-progress markers (the first two are requeued on restart); `ocr_paused`
# is a budget hold that `_reactivate_paused` flips back to `ocr_pending` when quota returns.
TRIGGER_STATUSES = ("uploaded", "ocr_pending", "committing")
_CJK = ("zh", "ja", "ko")

_JSON_FIELDS = {"detected_meta", "plan", "stats", "cost_estimate", "progress", "options"}

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
# One GPU behind the OCR sidecar → never run two OCR jobs at once (the worker is already
# sequential, but this also guards a future standalone worker process).
_OCR_LOCK = asyncio.Lock()


# ── Row (de)serialization ────────────────────────────────────────────────────

def _loads(v):
    """asyncpg returns JSONB as text here (no codec registered) — decode on read."""
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


async def create_job(format: str, original_path: str, file_sha256: str | None = None,
                     options: dict | None = None, detected_meta: dict | None = None,
                     status: str = "uploaded") -> int:
    """Insert a job row. Callers that already have the file on disk use the default
    'uploaded' status (the worker picks it up); the multipart upload path inserts as
    'receiving' first, saves the blob under the new id, then flips to 'uploaded'."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            """
            INSERT INTO import_jobs (format, original_path, file_sha256, options, detected_meta, status)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING id;
            """,
            format, original_path, file_sha256,
            json.dumps(options or {}), json.dumps(detected_meta or {}), status,
        ))


async def get_job(job_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM import_jobs WHERE id = $1;", job_id)
    return _row_to_job(row) if row else None


async def list_jobs(limit: int = 100) -> list[dict]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM import_jobs ORDER BY created_at DESC LIMIT $1;", limit
        )
    return [_row_to_job(r) for r in rows]


async def update_job(job_id: int, **fields) -> None:
    """Patch a job row. JSONB fields are json-dumped automatically; `updated_at` bumps."""
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
            f"UPDATE import_jobs SET {', '.join(sets)}, updated_at = now() WHERE id = ${len(args)};",
            *args,
        )


async def fail_job(job_id: int, error: str) -> None:
    logger.error(f"Import job {job_id} failed: {error}")
    await update_job(job_id, status="failed", error=str(error)[:4000])


# ── Stage handlers ───────────────────────────────────────────────────────────

async def _do_parse(job: dict) -> None:
    """uploaded → parse. EPUB and digital PDF go straight to review; a scanned PDF detours
    through the OCR cost-confirm gate. Heavy parser libs are imported here (not at module
    load) so the app boots even before the web deps land."""
    job_id = int(job["id"])
    fmt = job["format"]
    await update_job(job_id, status="parsing", stage="parsing", error=None)

    if fmt == "epub":
        from novelwiki.importer.parsers import epub as epub_parser
        document = epub_parser.parse_epub(job["original_path"], job_id)
        await _finish_parse(job_id, document)
    elif fmt == "pdf":
        from novelwiki.importer.parsers import pdf_text
        document = pdf_text.parse_pdf_text(job["original_path"], job_id)
        if document.meta.get("scanned"):
            await _enter_ocr_confirm(job_id, document, job)
        else:
            await _finish_parse(job_id, document)
    else:
        raise NotImplementedError(f"Format '{fmt}' is not handled.")


async def _finish_parse(job_id: int, document) -> None:
    """Shared tail for every parser: cleanup → segment → awaiting_review. Used by EPUB,
    digital PDF, and the post-OCR path."""
    from novelwiki.importer import cleanup, segment
    await update_job(job_id, stage="cleanup")
    cleanup.clean_document(document)
    storage.save_blocks(job_id, document)

    await update_job(job_id, stage="segmenting")
    plan = segment.build_plan(document)
    plan = await segment.refine_plan(plan, document)   # best-effort LLM pass; falls back silently

    stats = {
        "blocks": len(document.blocks),
        "segments": len(plan["segments"]),
        "images": len(document.meta.get("assets", {})),
        "words": sum(s.get("word_count", 0) for s in plan["segments"]),
    }
    if document.meta.get("ocr_stats"):
        stats["ocr"] = document.meta["ocr_stats"]
    await update_job(
        job_id,
        detected_meta=_public_meta(document.meta, job_id),
        plan=plan,
        stats=stats,
        status="awaiting_review",
        stage="awaiting review",
        error=None,
    )
    logger.info(f"Import job {job_id} parsed: {stats['segments']} segments, {stats['images']} images.")


# ── OCR (scanned PDF) ────────────────────────────────────────────────────────

async def _gemini_budget_remaining() -> int:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        used = await conn.fetchval(
            "SELECT used FROM provider_budget WHERE provider='gemini' AND day=CURRENT_DATE;"
        )
    return max(0, settings.GEMINI_DAILY_BUDGET - int(used or 0))


async def _enter_ocr_confirm(job_id: int, document, job: dict) -> None:
    """A scanned PDF is expensive, so we estimate the OCR cost and park the job behind a
    confirm gate instead of burning quota unprompted."""
    from novelwiki.importer.parsers import pdf_ocr
    options = job.get("options") or {}
    pages = document.meta.get("page_count", 0)
    est = pdf_ocr.estimate_cost(pages, bool(options.get("gemini_first")), await _gemini_budget_remaining())
    await update_job(
        job_id,
        status="awaiting_ocr_confirm",
        stage="awaiting OCR confirmation",
        cost_estimate=est,
        detected_meta=_public_meta(document.meta, job_id),
        stats={"page_count": pages, "scanned_pages": est["scanned_pages"]},
        error=None,
    )
    logger.info(f"Import job {job_id}: scanned PDF, {pages} pages — awaiting OCR confirmation.")


async def _do_ocr(job: dict) -> None:
    """ocr_pending → OCR (serialized on the GPU) → finish parse. A budget exhaustion parks
    the job in `ocr_paused`; per-page checkpoints mean it resumes where it left off."""
    job_id = int(job["id"])
    from novelwiki.importer.parsers import pdf_ocr
    from novelwiki.agent.llm_client import BudgetExhausted
    options = job.get("options") or {}

    async with _OCR_LOCK:
        await update_job(job_id, status="ocr_running", stage="OCR in progress", error=None)

        async def progress_cb(done, total):
            await update_job(job_id, progress={"done": done, "total": total, "unit": "pages"})

        try:
            document = await pdf_ocr.parse_pdf_ocr(job["original_path"], job_id, options, progress_cb)
        except BudgetExhausted:
            await update_job(job_id, status="ocr_paused",
                             stage="paused — Gemini daily budget reached; resumes tomorrow")
            logger.info(f"Import job {job_id} OCR paused on budget; will resume when quota rolls over.")
            return

    # CJK scans flow into the translation pipeline as a raw source (text == source language).
    if (document.meta.get("language") or "")[:2] in _CJK:
        await update_job(job_id, options={**options, "is_raw": True})
    await _finish_parse(job_id, document)


async def _do_commit(job: dict) -> None:
    """committing → write chapters/assets via the scraper persist path → committed."""
    job_id = int(job["id"])
    await update_job(job_id, stage="committing")
    from novelwiki.importer import commit
    result = await commit.commit_job(job)
    await update_job(
        job_id,
        novel_id=result["novel_id"],
        source_id=result.get("source_id"),
        status="committed",
        stage="committed",
        stats={**(job.get("stats") or {}), **result.get("stats", {})},
        error=None,
    )
    logger.info(f"Import job {job_id} committed → novel {result['novel_id']} "
                f"({result.get('stats', {}).get('chapters_written', 0)} chapters).")


def _public_meta(meta: dict, job_id: int) -> dict:
    """The metadata surfaced to the UI: book fields + a staged cover thumbnail URL."""
    out = {
        "title": meta.get("title"),
        "author": meta.get("author"),
        "language": meta.get("language"),
        "description": meta.get("description"),
        "series": meta.get("series"),
        "series_index": meta.get("series_index"),
    }
    cover_sha = meta.get("cover_sha")
    assets = meta.get("assets") or {}
    if cover_sha and cover_sha in assets:
        ext = assets[cover_sha].get("ext", "jpg")
        out["cover_sha"] = cover_sha
        out["cover_url"] = storage.staged_asset_url(job_id, cover_sha, ext)
    return out


# ── Worker loop ──────────────────────────────────────────────────────────────

async def _requeue_interrupted() -> None:
    """A deploy/restart can kill the worker mid-stage. `parsing`/`segmenting` reset to
    `uploaded` (re-parse cleanly); `ocr_running` resets to `ocr_pending` (resumes from the
    on-disk page checkpoints). `committing` jobs are left to be re-run (commit is idempotent)."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        n1 = await conn.execute(
            "UPDATE import_jobs SET status = 'uploaded', stage = 'requeued after restart' "
            "WHERE status IN ('parsing', 'segmenting');"
        )
        n2 = await conn.execute(
            "UPDATE import_jobs SET status = 'ocr_pending', stage = 'resuming OCR after restart' "
            "WHERE status = 'ocr_running';"
        )
    for n in (n1, n2):
        if n and not n.endswith(" 0"):
            logger.info(f"Requeued interrupted import jobs: {n}.")


async def _reactivate_paused() -> None:
    """Unpause budget-held OCR jobs once Gemini quota is available again (e.g. the daily
    counter reset overnight). One cheap statement per tick; a no-op when nothing is paused."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE import_jobs SET status='ocr_pending', stage='resuming OCR (budget available)'
            WHERE status='ocr_paused'
              AND COALESCE((SELECT used FROM provider_budget WHERE provider='gemini' AND day=CURRENT_DATE), 0) < $1;
            """,
            settings.GEMINI_DAILY_BUDGET,
        )


async def _claim_next() -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT * FROM import_jobs WHERE status = ANY($1::text[]) "
            f"ORDER BY updated_at ASC LIMIT 1;",
            list(TRIGGER_STATUSES),
        )
    return _row_to_job(row) if row else None


async def _process(job: dict) -> None:
    job_id = int(job["id"])
    try:
        if job["status"] == "uploaded":
            await _do_parse(job)
        elif job["status"] == "ocr_pending":
            await _do_ocr(job)
        elif job["status"] == "committing":
            await _do_commit(job)
    except Exception as e:
        logger.exception(f"Import job {job_id} crashed during '{job['status']}'.")
        await fail_job(job_id, f"{type(e).__name__}: {e}")


async def worker_loop(poll_interval: float = 2.0) -> None:
    storage.ensure_dirs()
    try:
        await _requeue_interrupted()
    except Exception as e:
        logger.warning(f"Import worker: could not requeue interrupted jobs: {e}")
    logger.info("Import worker started.")
    while not _stop.is_set():
        try:
            await _reactivate_paused()      # unpause budget-held OCR jobs when quota returns
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
            logger.warning(f"Import worker loop error: {e}")
            try:
                await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
    logger.info("Import worker stopped.")


def start_worker() -> None:
    """Launch the background worker (idempotent). Called from the FastAPI lifespan."""
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
