"""Durable import-job state machine + the worker that drives it.

A deploy here is an image rebuild, which kills any in-process work, and OCR can span
days under the Gemini free-tier quota — so import state lives in ``import_jobs`` and a
single DB-polled worker (started from the app lifespan) advances jobs across restarts.

State machine (S1 path; OCR states land in S3)::

    uploaded ──claim──▶ parsing ──▶ awaiting_review ──commit──▶ committing ──claim──▶ commit_running ──▶ committed
       ▲                                                                                  │
       └────────── (restart / stale-lease requeues an interrupted in-progress job) ───────┘
    any ──▶ failed | canceled

Claiming is atomic AND leased: ``_claim_next`` moves a trigger status to its distinct
in-progress marker (uploaded→parsing, ocr_pending→ocr_running, committing→commit_running) in
one ``UPDATE … FOR UPDATE SKIP LOCKED`` and stamps the claiming worker's opaque token +
``claimed_at``. The markers are NOT trigger states, so a claimed job leaves the queue the
instant it's claimed (this is what makes a committing job safe against a concurrent
double-commit). While it works, the worker renews ``claimed_at`` on a heartbeat; recovery
(``_recover_stale_leases``) requeues an in-progress job ONLY once its lease has gone unrenewed
past the timeout — i.e. the owning worker is provably gone. There is deliberately no
unconditional "requeue everything on boot" step: that would yank jobs a sibling worker is
actively processing, which is exactly the multi-worker double-claim we must avoid.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import timedelta

from novelwiki.platform.config import settings
from novelwiki.modules.acquisition.adapters.outbound.importer import storage

logger = logging.getLogger(__name__)

# Statuses the worker actively advances (trigger states). Each is claimed atomically into a
# distinct in-progress marker: `parsing`/`ocr_running`/`commit_running`. `ocr_paused` is a
# budget hold that `_reactivate_paused` flips back to `ocr_pending` when quota returns.
TRIGGER_STATUSES = ("uploaded", "ocr_pending", "committing")
# In-progress markers → the trigger status a lease-expired job resumes to. (`segmenting` is
# a legacy marker kept for defence; today it only ever appears as a *stage*, not a status.)
_MARKER_RESUME = (
    (("parsing", "segmenting"), "uploaded"),
    (("ocr_running",), "ocr_pending"),
    (("commit_running",), "committing"),
)
_CJK = ("zh", "ja", "ko")

# Opaque per-process identity stamped on claimed jobs. Freshly minted each process start, so a
# restarted worker never mistakes a previous incarnation's live-looking claim for its own.
_WORKER_ID = uuid.uuid4().hex

# How often the worker runs its (cheap) maintenance sweeps: lease recovery + abandoned-upload
# GC. Kept above the poll interval but well under the lease timeout so an orphaned job is
# reclaimed promptly after its lease expires.
_MAINTENANCE_INTERVAL_SECONDS = 60.0
_last_maintenance = 0.0

_JSON_FIELDS = {"detected_meta", "plan", "stats", "cost_estimate", "progress", "options"}


def _looks_raw(language: str | None) -> bool:
    """A book whose own text isn't English is a raw the reader should translate on demand.
    Used to pre-set ``options.is_raw`` after parsing; the review UI can still override it."""
    lang = (language or "").strip().lower()
    return bool(lang) and not lang.startswith("en")

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
# One GPU behind the OCR sidecar → never run two OCR jobs at once (the worker is already
# sequential, but this also guards a future standalone worker process).
_OCR_LOCK = asyncio.Lock()


async def _worker_repository():
    from novelwiki.bootstrap.acquisition import build_import_worker_repository
    return await build_import_worker_repository()


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


async def _job_owner_can_spend(job: dict) -> bool:
    """Queued jobs may have been created before the current route guards. Re-check the
    owner before parser/OCR work that can spend API budget."""
    user_id = job.get("user_id")
    if user_id is None:
        return True
    from novelwiki.bootstrap.acquisition import import_worker_owner_can_spend
    return await import_worker_owner_can_spend(user_id)


async def create_job(format: str, original_path: str, file_sha256: str | None = None,
                     options: dict | None = None, detected_meta: dict | None = None,
                     status: str = "uploaded", user_id: int | None = None) -> int:
    """Insert a job row owned by `user_id` (the uploader). Callers that already have the file
    on disk use the default 'uploaded' status (the worker picks it up); the multipart upload
    path inserts as 'receiving' first, saves the blob under the new id, then flips to 'uploaded'."""
    return await (await _worker_repository()).create_job(
        format, original_path, file_sha256, options or {}, detected_meta or {},
        status, user_id,
    )


async def get_job(job_id: int) -> dict | None:
    row = await (await _worker_repository()).get_job(job_id)
    return _row_to_job(row) if row else None


async def list_jobs(limit: int = 100, user_id: int | None = None) -> list[dict]:
    """All jobs (admin) or only those owned by `user_id`."""
    rows = await (await _worker_repository()).list_jobs(limit, user_id)
    return [_row_to_job(r) for r in rows]


async def update_job(job_id: int, **fields) -> None:
    """Patch a job row. JSONB fields are json-dumped automatically; `updated_at` bumps."""
    if not fields:
        return
    await (await _worker_repository()).update_job(job_id, fields)


async def fail_job(job_id: int, error: str) -> None:
    logger.error(f"Import job {job_id} failed: {error}")
    await update_job(job_id, status="failed", error=str(error)[:4000])


async def touch_job(job_id: int) -> None:
    """Bump ``updated_at`` alone — marks a `receiving` upload session as still alive so its chunks
    still arriving don't let the abandoned-session sweep read it as dead."""
    await (await _worker_repository()).touch_job(job_id)


# ── Stage handlers ───────────────────────────────────────────────────────────

async def _do_parse(job: dict) -> None:
    """uploaded → parse. EPUB and digital PDF go straight to review; a scanned PDF detours
    through the OCR cost-confirm gate. Heavy parser libs are imported here (not at module
    load) so the app boots even before the web deps land."""
    job_id = int(job["id"])
    fmt = job["format"]
    await update_job(job_id, status="parsing", stage="parsing", error=None)

    if fmt == "epub":
        from novelwiki.modules.acquisition.adapters.outbound.importer.parsers import epub as epub_parser
        document = epub_parser.parse_epub(job["original_path"], job_id)
        await _finish_parse(job_id, document)
    elif fmt == "pdf":
        from novelwiki.modules.acquisition.adapters.outbound.importer.parsers import pdf_text
        document = pdf_text.parse_pdf_text(job["original_path"], job_id)
        if document.meta.get("scanned"):
            await _enter_ocr_confirm(job_id, document, job)
        else:
            await _finish_parse(job_id, document)
    else:
        raise NotImplementedError(f"Format '{fmt}' is not handled.")


async def _finish_parse(job_id: int, document) -> None:
    """Shared tail for every parser: cleanup → segment → quality → awaiting_review. Used by
    EPUB, digital PDF, and the post-OCR path. A batch job with ``auto_commit`` is advanced
    straight past review."""
    from novelwiki.modules.acquisition.adapters.outbound.importer import segment
    from novelwiki.modules.acquisition.domain import cleanup, quality
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
        "quality": quality.compute_quality(document, plan),
    }
    if document.meta.get("ocr_stats"):
        stats["ocr"] = document.meta["ocr_stats"]

    # Auto-flag a non-English book as a raw so it lands in the on-demand translation pipeline.
    # The OCR path may already have set this for a CJK scan; if so, keep it. The review UI
    # surfaces this as a pre-checked toggle the user can still flip before committing.
    job = await get_job(job_id)
    options = (job or {}).get("options") or {}
    if "is_raw" not in options and _looks_raw(document.meta.get("language")):
        options = {**options, "is_raw": True}

    await update_job(
        job_id,
        options=options,
        detected_meta=_public_meta(document.meta, job_id),
        plan=plan,
        stats=stats,
        status="awaiting_review",
        stage="awaiting review",
        error=None,
    )
    logger.info(f"Import job {job_id} parsed: {stats['segments']} segments, {stats['images']} images, "
                f"quality {stats['quality']['score']}.")
    await _auto_advance(job_id)


# States a batch sibling passes through on its own before it reaches review — while any
# sibling is still in one of these, a `group_series` batch waits before committing the group.
# (awaiting_ocr_confirm is excluded: it needs a human, so it never blocks the rest.)
_PRE_REVIEW = ("receiving", "uploaded", "parsing", "segmenting",
               "ocr_pending", "ocr_running", "ocr_paused")


async def _batch_siblings(batch_id: str) -> list[dict]:
    if not batch_id:
        return []
    rows = await (await _worker_repository()).batch_siblings(batch_id)
    return [_row_to_job(r) for r in rows]


async def _auto_advance(job_id: int) -> None:
    """Honour ``options.auto_commit`` for folder/batch imports. Without ``group_series`` each
    book commits to its own new novel; with it, once every auto-progressing sibling in the
    batch has reached review, siblings are grouped by detected series and each multi-volume
    group is committed into a single novel (others commit individually)."""
    job = await get_job(job_id)
    options = (job or {}).get("options") or {}
    if not options.get("auto_commit"):
        return
    if not options.get("group_series"):
        await update_job(job_id, status="committing", stage="auto-committing")
        return

    siblings = await _batch_siblings(options.get("batch_id"))
    if any(s["status"] in _PRE_REVIEW for s in siblings):
        return  # the last straggler to finish parsing will trigger the grouped commit

    ready = [s for s in siblings if s["status"] == "awaiting_review"]
    groups: dict[str, list[dict]] = {}
    for s in ready:
        series = ((s.get("detected_meta") or {}).get("series") or "").strip()
        groups.setdefault(series or f"__single_{s['id']}", []).append(s)

    from novelwiki.modules.acquisition.adapters.outbound.importer import commit
    for key, grp in groups.items():
        ids = [int(s["id"]) for s in grp]
        if key.startswith("__single_") or len(ids) == 1:
            await update_job(ids[0], status="committing", stage="auto-committing")
            continue
        try:
            await commit.commit_series(ids)
            logger.info(f"Auto-committed series '{key}' ({len(ids)} volumes) from batch.")
        except Exception as e:
            logger.warning(f"Series auto-commit failed for '{key}': {e}")
            for jid in ids:
                await fail_job(jid, f"series commit: {type(e).__name__}: {e}")


async def imports_with_hash(file_sha256: str, exclude_job_id: int | None = None) -> list[dict]:
    """Prior import jobs for the same file bytes (re-import detection). Most-recent first;
    callers surface committed ones as a 'you already imported this' warning."""
    if not file_sha256:
        return []
    rows = await (await _worker_repository()).duplicate_imports(
        file_sha256, exclude_job_id
    )
    from novelwiki.bootstrap.acquisition import import_job_novel_titles
    titles = await import_job_novel_titles({
        int(row["novel_id"]) for row in rows if row["novel_id"] is not None
    })
    return [
        {
            "job_id": int(r["id"]),
            "novel_id": int(r["novel_id"]) if r["novel_id"] is not None else None,
            "novel_title": titles.get(int(r["novel_id"])) if r["novel_id"] is not None else None,
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


# ── OCR (scanned PDF) ────────────────────────────────────────────────────────

async def _gemini_budget_remaining() -> int:
    from novelwiki.bootstrap.acquisition import gemini_budget_remaining
    return await gemini_budget_remaining()


async def _enter_ocr_confirm(job_id: int, document, job: dict) -> None:
    """A scanned PDF is expensive, so we estimate the OCR cost and park the job behind a
    confirm gate instead of burning quota unprompted."""
    from novelwiki.modules.acquisition.adapters.outbound.importer.parsers import pdf_ocr
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
    from novelwiki.modules.acquisition.adapters.outbound.importer.parsers import pdf_ocr
    from novelwiki.modules.ai_execution.public import BudgetExhausted
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
    """commit_running → write chapters/assets via the scraper persist path → committed.

    ``commit_job`` records completion (novel_id + status='committed') INSIDE its own
    transaction, so this stage is crash-safe: if a restart interrupts a commit, the work
    either fully rolled back (requeued `committing` re-runs clean) or fully landed as
    'committed' (a terminal state, never re-run) — a duplicate novel can't slip through the
    gap. The atomic claim also guarantees only one worker is ever in this stage for a job."""
    job_id = int(job["id"])
    await update_job(job_id, stage="committing")
    from novelwiki.modules.acquisition.adapters.outbound.importer import commit
    result = await commit.commit_job(job)
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

async def _recover_stale_leases() -> None:
    """Requeue in-progress jobs whose lease has expired — i.e. the owning worker stopped renewing
    ``claimed_at`` (crashed, was killed mid-deploy, lost the DB). This is the ONLY recovery path,
    and it is multi-worker safe: a *live* worker heartbeats its claim, so a job it is actively
    processing never looks reclaimable and is never yanked out from under it. Each expired marker
    goes back to its trigger status with the claim cleared (a NULL lease = orphaned marker, also
    reclaimable). Resuming is clean: re-parse from scratch, OCR from on-disk page checkpoints,
    re-run the idempotent + crash-safe commit."""
    lease = timedelta(seconds=settings.IMPORT_LEASE_TIMEOUT_SECONDS)
    repository = await _worker_repository()
    for markers, trigger in _MARKER_RESUME:
        result = await repository.recover_stale_leases(markers, trigger, lease)
        if result and not result.endswith(" 0"):
            logger.info(f"Recovered orphaned import leases → {trigger}: {result}.")


async def _cleanup_stale_uploads() -> None:
    """GC abandoned resumable-upload sessions: a job stuck in `receiving` past the TTL had its
    client walk away mid-upload, so its partial blob is dead weight (a disk-fill lever if left
    unbounded). The DELETE re-checks the stale predicate so a session that received a fresh chunk
    between the scan and the delete (its ``updated_at`` bumped, see ``touch_job``) is left alone."""
    ttl = timedelta(hours=settings.IMPORT_UPLOAD_SESSION_TTL_HOURS)
    removed = 0
    repository = await _worker_repository()
    for job_id in await repository.stale_upload_ids(ttl):
        if not await repository.delete_stale_upload(job_id, ttl):
            continue
        try:
            storage.cleanup_job(job_id)
        except Exception as e:
            logger.warning(f"Cleanup of abandoned upload {job_id} left files behind: {e}")
        removed += 1
    if removed:
        logger.info(f"Cleaned up {removed} abandoned upload session(s).")


async def _run_maintenance(force: bool = False) -> None:
    """Throttled housekeeping (lease recovery + abandoned-upload GC), safe to call every tick —
    it only does real work every `_MAINTENANCE_INTERVAL_SECONDS` (or when `force`)."""
    global _last_maintenance
    now = time.monotonic()
    if not force and (now - _last_maintenance) < _MAINTENANCE_INTERVAL_SECONDS:
        return
    _last_maintenance = now
    await _recover_stale_leases()
    await _cleanup_stale_uploads()


async def _reactivate_paused() -> None:
    """Unpause budget-held OCR jobs once Gemini quota is available again (e.g. the daily
    counter reset overnight). One cheap statement per tick; a no-op when nothing is paused."""
    if await _gemini_budget_remaining() > 0:
        await (await _worker_repository()).reactivate_paused()


async def _claim_next() -> dict | None:
    """Atomically claim the oldest pending job, moving it from its trigger status to the matching
    in-progress marker in a single locked statement (mirrors the TTS worker) and stamping this
    worker's lease (`claim_token` + `claimed_at`). Because the marker is not a trigger status, the
    job leaves the queue the instant it's claimed, so two workers can never process the same job.
    The returned row already carries the new in-progress status, which `_process` dispatches on."""
    row = await (await _worker_repository()).claim_next(
        TRIGGER_STATUSES, _WORKER_ID
    )
    return _row_to_job(row) if row else None


async def _renew_lease(job_id: int, token: str | None) -> None:
    """Bump `claimed_at` on a job we still hold, guarded by `claim_token` so we never steal back a
    lease that recovery already handed to another worker."""
    if not token:
        return
    await (await _worker_repository()).renew_lease(job_id, token)


async def _heartbeat(job_id: int, token: str | None, stop: asyncio.Event) -> None:
    """Renew the lease every `IMPORT_WORKER_HEARTBEAT_SECONDS` for as long as `_process` runs, so a
    long stage (OCR especially) keeps its claim alive and the recovery sweep leaves it be. Runs
    concurrently with the stage; DB hiccups are swallowed (a missed beat just shortens the lease)."""
    interval = max(5, settings.IMPORT_WORKER_HEARTBEAT_SECONDS)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return                          # stop signalled → stage finished
        except asyncio.TimeoutError:
            pass
        try:
            await _renew_lease(job_id, token)
        except Exception as e:
            logger.debug(f"Import job {job_id} lease heartbeat skipped: {e}")


async def _process(job: dict) -> None:
    job_id = int(job["id"])
    status = job["status"]              # already the in-progress marker set by the atomic claim
    token = job.get("claim_token")
    stop_hb = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(job_id, token, stop_hb))
    try:
        if status == "parsing":
            if not await _job_owner_can_spend(job):
                await fail_job(job_id, "Verify your email before importing files.")
                return
            await _do_parse(job)
        elif status == "ocr_running":
            if not await _job_owner_can_spend(job):
                await fail_job(job_id, "Verify your email before running OCR.")
                return
            await _do_ocr(job)
        elif status == "commit_running":
            await _do_commit(job)
    except Exception as e:
        logger.exception(f"Import job {job_id} crashed during '{status}'.")
        await fail_job(job_id, f"{type(e).__name__}: {e}")
    finally:
        stop_hb.set()
        try:
            await heartbeat
        except Exception:
            pass


async def worker_loop(poll_interval: float = 2.0) -> None:
    storage.ensure_dirs()
    # No unconditional "requeue everything" on boot — that would reclaim jobs a sibling worker is
    # actively processing. Recovery is purely lease-expiry based (multi-worker safe).
    try:
        await _run_maintenance(force=True)  # reclaim lease-expired jobs + GC abandoned uploads
    except Exception as e:
        logger.warning(f"Import worker: startup maintenance failed: {e}")
    logger.info("Import worker started.")
    while not _stop.is_set():
        try:
            await _reactivate_paused()      # unpause budget-held OCR jobs when quota returns
            await _run_maintenance()        # throttled: stale-lease recovery + abandoned-upload GC
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
