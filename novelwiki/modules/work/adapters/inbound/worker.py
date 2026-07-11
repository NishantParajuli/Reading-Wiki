"""Durable worker for generic background jobs (scrape / codex build / translation).

Mirrors the import + TTS workers (novelwiki/importer/jobs.py, novelwiki/tts/worker.py): job state
lives in the ``jobs`` table and a single DB-polled background task (started from the app lifespan)
advances jobs across process restarts. This is what lets scrape/codex/translation survive a deploy
after quota was already reserved — the work that used to run in fire-and-forget ``BackgroundTasks``.

Claiming is atomic AND leased: ``_claim_next`` moves ``queued`` → ``running`` in one
``UPDATE … FOR UPDATE SKIP LOCKED``, increments ``attempts``, and stamps the claiming worker's
opaque token + ``claimed_at``. ``running`` is not a trigger status, so a claimed job leaves the
queue the instant it's claimed — two workers can never run the same job. While it works the worker
heartbeats ``claimed_at``; ``_recover_stale_leases`` only reclaims a job whose lease has gone
unrenewed past the timeout (i.e. the owning worker is provably gone), retrying it or failing it once
its attempts are exhausted. There is deliberately no "requeue everything on boot" step.

Cancellation is cooperative: a route flips the job to ``canceled`` and the running handler notices
between stages/chapters and unwinds, keeping any work already finished. Quota is finalized (refunded
if unconsumed) exactly once at every terminal state — see ``service.finalize``.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import timedelta

from novelwiki import audit, quota
from novelwiki.config.settings import settings
from novelwiki.jobs import service
from novelwiki.jobs.claims import claim_next
from novelwiki.modules.work.application import WorkerStateService

logger = logging.getLogger(__name__)

# Opaque per-process identity stamped on claimed jobs — freshly minted each start, so a restarted
# worker never mistakes a previous incarnation's live-looking claim for its own.
_WORKER_ID = uuid.uuid4().hex

_MAINTENANCE_INTERVAL_SECONDS = 60.0
_last_maintenance = 0.0

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()
async def _worker_state() -> WorkerStateService:
    from novelwiki.bootstrap.work_worker import build_worker_state_service

    # Pool ownership belongs to Platform and test/application lifecycles may replace
    # it. Rebuild this lightweight facade so it always points at the active pool.
    return await build_worker_state_service()


# ── User + cancellation helpers ──────────────────────────────────────────────

async def _load_user(user_id: int | None) -> dict | None:
    return await (await _worker_state()).load_user(user_id)


class _Canceled(Exception):
    """Raised by a handler's cancel check to unwind cleanly to the canceled terminal state."""


async def _bail_if_canceled(job_id: int) -> None:
    if await service.is_canceled(job_id):
        raise _Canceled()


# ── Handlers (dispatch by kind) ──────────────────────────────────────────────

async def _handle_scrape(job: dict) -> dict:
    """Scrape one source (ownership-checked via expected_novel_id) or every source of the novel."""
    from novelwiki.scraper.runner import scrape_source, scrape_novel
    job_id = int(job["id"])
    novel_id = int(job["novel_id"])
    opts = job.get("options") or {}
    source_id = opts.get("source_id")
    force = bool(opts.get("force"))
    max_chapters = opts.get("max_chapters")
    await _bail_if_canceled(job_id)
    await service.update_job(job_id, stage="scraping")
    if source_id is not None:
        scraped = await scrape_source(int(source_id), force=force, max_chapters=max_chapters,
                                      expected_novel_id=novel_id,
                                      cancel_check=lambda: _bail_if_canceled(job_id))
    else:
        scraped = await scrape_novel(novel_id, force=force, max_chapters=max_chapters,
                                     cancel_check=lambda: _bail_if_canceled(job_id))
    await _bail_if_canceled(job_id)
    return {"scraped": int(scraped)}


async def _handle_codex(job: dict) -> dict:
    """Full codex pipeline with progress stages + cancellation checks between them."""
    from novelwiki.ingest.chunk import chunk_all_chapters
    from novelwiki.ingest.embed import embed_missing_chunks
    from novelwiki.ingest.extract import extract_all_chapters
    from novelwiki.retrieval.bm25 import get_bm25_manager
    job_id = int(job["id"])
    novel_id = int(job["novel_id"])
    opts = job.get("options") or {}
    force = bool(opts.get("force"))
    frm = opts.get("from_chapter")
    to = opts.get("to_chapter")

    steps = 4
    await service.set_progress(job_id, {"step": 1, "steps": steps, "stage": "chunking"}, stage="chunking")
    cancel_check = lambda: _bail_if_canceled(job_id)
    await chunk_all_chapters(
        novel_id, force=force, from_chapter=frm, to_chapter=to, cancel_check=cancel_check,
    )
    await _bail_if_canceled(job_id)

    await service.set_progress(job_id, {"step": 2, "steps": steps, "stage": "embedding"}, stage="embedding")
    await embed_missing_chunks(
        novel_id, from_chapter=frm, to_chapter=to, cancel_check=cancel_check,
    )
    await _bail_if_canceled(job_id)

    await service.set_progress(job_id, {"step": 3, "steps": steps, "stage": "extracting"}, stage="extracting")
    await extract_all_chapters(
        novel_id, force=force, from_chapter=frm, to_chapter=to, cancel_check=cancel_check,
    )
    await _bail_if_canceled(job_id)

    await service.set_progress(job_id, {"step": 4, "steps": steps, "stage": "indexing"}, stage="indexing")
    await get_bm25_manager(novel_id).rebuild()
    return {"step": steps, "steps": steps}


async def _pending_translations(novel_id: int, frm, to, force: bool) -> list[float]:
    return await (await _worker_state()).pending_translations(
        novel_id, frm, to, force
    )


async def _handle_translate(job: dict) -> dict:
    """Translate the pending raw chapters in range, computed at execution time, metering per chapter.

    Cancellation is checked between chapters (keeping ones already translated), and a mid-batch quota
    exhaustion stops the job gracefully. Optionally seeds the glossary from the codex first."""
    from novelwiki.translate.translate import translate_chapter, seed_glossary_from_entities
    job_id = int(job["id"])
    novel_id = int(job["novel_id"])
    opts = job.get("options") or {}
    force = bool(opts.get("force"))
    frm = opts.get("from_chapter")
    to = opts.get("to_chapter")

    user = await _load_user(job.get("user_id"))
    if user is None or not quota.spend_allowed(user):
        raise RuntimeError("Verify your email before running a translation batch.")

    if opts.get("seed_from_codex"):
        await service.update_job(job_id, stage="seeding glossary")
        await seed_glossary_from_entities(novel_id)

    chapters = await _pending_translations(novel_id, frm, to, force)
    total = len(chapters)
    done = failed = 0
    await service.set_progress(job_id, {"done": 0, "total": total}, stage="translating")
    for i, number in enumerate(chapters):
        await _bail_if_canceled(job_id)
        res = await translate_chapter(novel_id, number, force=force, meter_user=user)
        status = res.get("status")
        if status == "quota_exceeded":
            await service.set_progress(
                job_id, {"done": done, "failed": failed, "total": total, "stopped_reason": "quota"})
            return {"done": done, "failed": failed, "total": total, "stopped_reason": "quota"}
        if status == "done":
            done += 1
        elif status == "failed":
            failed += 1
        await service.set_progress(
            job_id, {"done": done, "failed": failed, "total": total, "current_chapter": number})
    return {"done": done, "failed": failed, "total": total}


_HANDLERS = {
    "scrape": _handle_scrape,
    "codex_build": _handle_codex,
    "translate": _handle_translate,
}


# ── Claim / lease / recovery ─────────────────────────────────────────────────

async def _claim_next() -> dict | None:
    """Atomically claim the oldest queued job → ``running``, bump attempts, and stamp this worker's
    lease. The marker is not a trigger status, so the job leaves the queue the instant it's claimed."""
    return await claim_next(execution_backend="api", worker_id=_WORKER_ID)


async def _renew_lease(job_id: int, token: str | None) -> None:
    await (await _worker_state()).renew_lease(job_id, token)


async def _heartbeat(job_id: int, token: str | None, stop: asyncio.Event) -> None:
    interval = max(5, settings.JOB_WORKER_HEARTBEAT_SECONDS)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await _renew_lease(job_id, token)
        except Exception as e:
            logger.debug(f"Job {job_id} lease heartbeat skipped: {e}")


async def _recover_stale_leases() -> None:
    """Reclaim ``running`` jobs whose lease expired (the owning worker crashed/was killed). Multi-worker
    safe: a live worker heartbeats its claim, so a job it is actively processing never looks reclaimable.
    A reclaimed job is retried while attempts remain, else failed once and quota-finalized."""
    lease = timedelta(seconds=settings.JOB_LEASE_TIMEOUT_SECONDS)
    recoveries = await (await _worker_state()).recover_stale_leases(lease)
    for recovery in recoveries:
        job_id = recovery.job_id
        if recovery.action == "canceled":
            await service.finalize(job_id, success=False)
            await audit.record(
                "job.canceled",
                data={"job_id": job_id, "reason": "lease_expired_after_cancel"},
            )
        elif recovery.action == "failed":
            logger.warning(
                f"Job {job_id} failed after lease expiry (attempts exhausted)."
            )
            await service.finalize(job_id, success=False)
            await audit.record(
                "job.failed", data={"job_id": job_id, "reason": "lease_expired"}
            )
        else:
            logger.info(f"Recovered orphaned job {job_id} → queued (lease expired).")


async def _release_due_provider_waits() -> None:
    """A provider-wait row has no lease; make due rows claimable again."""
    await (await _worker_state()).release_due_provider_waits()


async def _run_maintenance(force: bool = False) -> None:
    global _last_maintenance
    now = time.monotonic()
    if not force and (now - _last_maintenance) < _MAINTENANCE_INTERVAL_SECONDS:
        return
    _last_maintenance = now
    await _release_due_provider_waits()
    await _recover_stale_leases()


# ── Process one job ──────────────────────────────────────────────────────────

async def _process(job: dict) -> None:
    job_id = int(job["id"])
    kind = job["kind"]
    token = job.get("claim_token")
    handler = _HANDLERS.get(kind)
    stop_hb = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(job_id, token, stop_hb))
    try:
        if handler is None:
            await service.fail_or_retry(job, f"Unknown job kind '{kind}'.")
            return
        try:
            progress = await handler(job)
        except _Canceled:
            logger.info(f"Job {job_id} ({kind}) canceled mid-run.")
            await service.finalize(job_id, success=False)
            return
        # Completed the work. Mark done unless a cancel won the race; either way finalize quota.
        if await service.mark_done_if_running(job_id, progress=progress):
            await service.finalize(job_id, success=True)
            logger.info(f"Job {job_id} ({kind}) done.")
            await audit.record("job.done", user_id=job.get("user_id"), novel_id=job.get("novel_id"),
                               data={"job_id": job_id, "kind": kind})
        else:
            await service.finalize(job_id, success=False)
    except Exception as e:
        logger.exception(f"Job {job_id} ({kind}) crashed.")
        await service.fail_or_retry(job, f"{type(e).__name__}: {e}")
    finally:
        stop_hb.set()
        try:
            await heartbeat
        except Exception:
            pass


# ── Worker loop ──────────────────────────────────────────────────────────────

async def worker_loop(poll_interval: float = 2.0) -> None:
    try:
        await _run_maintenance(force=True)
    except Exception as e:
        logger.warning(f"Jobs worker: startup maintenance failed: {e}")
    logger.info("Jobs worker started.")
    while not _stop.is_set():
        try:
            await _run_maintenance()
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
            logger.warning(f"Jobs worker loop error: {e}")
            try:
                await asyncio.wait_for(_stop.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
    logger.info("Jobs worker stopped.")


def start_worker() -> None:
    """Launch the background jobs worker (idempotent). Called from the FastAPI lifespan."""
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
