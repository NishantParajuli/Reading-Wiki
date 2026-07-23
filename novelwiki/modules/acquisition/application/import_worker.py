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

logger = logging.getLogger(__name__)


def _log_event(level: int, event: str, message: str, **fields) -> None:
    """Emit adapter-neutral event metadata without coupling Application to Platform."""
    logger.log(
        level, message, extra={"event": event, "event_fields": fields}, stacklevel=2
    )

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

# How often the worker runs its (cheap) maintenance sweeps: lease recovery + abandoned-upload
# GC. Kept above the poll interval but well under the lease timeout so an orphaned job is
# reclaimed promptly after its lease expires.
_JSON_FIELDS = {"detected_meta", "plan", "stats", "cost_estimate", "progress", "options"}


def _looks_raw(language: str | None) -> bool:
    """A book whose own text isn't English is a raw the reader should translate on demand.
    Used to pre-set ``options.is_raw`` after parsing; the review UI can still override it."""
    lang = (language or "").strip().lower()
    return bool(lang) and not lang.startswith("en")

# One GPU behind the OCR sidecar → never run two OCR jobs at once (the worker is already
# sequential, but this also guards a future standalone worker process).
_OCR_LOCK = asyncio.Lock()


async def _worker_repository(runtime):
    return await runtime.import_repository()


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


async def _job_owner_can_spend(job: dict, runtime) -> bool:
    """Queued jobs may have been created before the current route guards. Re-check the
    owner before parser/OCR work that can spend API budget."""
    user_id = job.get("user_id")
    if user_id is None:
        return True
    return await runtime.owner_can_spend(user_id)


async def create_job(format: str, original_path: str, file_sha256: str | None = None,
                     options: dict | None = None, detected_meta: dict | None = None,
                     status: str = "uploaded", user_id: int | None = None, *, runtime) -> int:
    """Insert a job row owned by `user_id` (the uploader). Callers that already have the file
    on disk use the default 'uploaded' status (the worker picks it up); the multipart upload
    path inserts as 'receiving' first, saves the blob under the new id, then flips to 'uploaded'."""
    job_id = await (await _worker_repository(runtime)).create_job(
        format, original_path, file_sha256, options or {}, detected_meta or {},
        status, user_id,
    )
    _log_event(
        logging.INFO, "import_job.created",
        f"Created {format} import job {job_id} with status {status}.",
        job_system="import", job_id=job_id, job_kind=f"import_{format}",
        job_format=format, user_id=user_id, status=status,
        file_sha256_prefix=(file_sha256 or "")[:12] or None,
        auto_commit=bool((options or {}).get("auto_commit")),
        batch_id=(options or {}).get("batch_id"),
    )
    return job_id


async def get_job(job_id: int, *, runtime) -> dict | None:
    row = await (await _worker_repository(runtime)).get_job(job_id)
    return _row_to_job(row) if row else None


async def list_jobs(
    limit: int = 100, user_id: int | None = None, *, runtime
) -> list[dict]:
    """All jobs (admin) or only those owned by `user_id`."""
    rows = await (await _worker_repository(runtime)).list_jobs(limit, user_id)
    return [_row_to_job(r) for r in rows]


async def update_job(job_id: int, *, runtime, **fields) -> None:
    """Patch a job row. JSONB fields are json-dumped automatically; `updated_at` bumps."""
    if not fields:
        return
    await (await _worker_repository(runtime)).update_job(job_id, fields)
    state_fields = {"status", "stage", "progress"} & fields.keys()
    if state_fields:
        _log_event(
            logging.INFO, "import_job.state_changed",
            f"Import job {job_id} state changed"
            f"{f' to {fields.get("status")}' if fields.get('status') else ''}.",
            job_system="import", job_id=job_id, status=fields.get("status"),
            stage=fields.get("stage"), progress=fields.get("progress"),
            changed_fields=sorted(fields),
        )


async def fail_job(job_id: int, error: str, *, runtime) -> None:
    _log_event(
        logging.ERROR, "import_job.failed", f"Import job {job_id} failed.",
        job_system="import", job_id=job_id, error=str(error)[:4000],
    )
    await update_job(
        job_id, status="failed", error=str(error)[:4000], runtime=runtime
    )


async def touch_job(job_id: int, *, runtime) -> None:
    """Bump ``updated_at`` alone — marks a `receiving` upload session as still alive so its chunks
    still arriving don't let the abandoned-session sweep read it as dead."""
    await (await _worker_repository(runtime)).touch_job(job_id)


# ── Stage handlers ───────────────────────────────────────────────────────────

async def do_parse(job: dict, *, runtime) -> None:
    """uploaded → parse. EPUB and digital PDF go straight to review; a scanned PDF detours
    through the OCR cost-confirm gate. Heavy parser libs are imported here (not at module
    load) so the app boots even before the web deps land."""
    job_id = int(job["id"])
    fmt = job["format"]
    await update_job(
        job_id, status="parsing", stage="parsing", error=None, runtime=runtime
    )

    if fmt == "epub":
        document = runtime.parse_epub(job["original_path"], job_id)
        await _finish_parse(job_id, document, runtime=runtime)
    elif fmt == "pdf":
        document = runtime.parse_pdf_text(job["original_path"], job_id)
        if document.meta.get("scanned"):
            await _enter_ocr_confirm(job_id, document, job, runtime=runtime)
        else:
            await _finish_parse(job_id, document, runtime=runtime)
    else:
        raise NotImplementedError(f"Format '{fmt}' is not handled.")


async def _finish_parse(job_id: int, document, *, runtime) -> None:
    """Shared tail for every parser: cleanup → segment → quality → awaiting_review. Used by
    EPUB, digital PDF, and the post-OCR path. A batch job with ``auto_commit`` is advanced
    straight past review."""
    from novelwiki.modules.acquisition.domain import cleanup, quality
    await update_job(job_id, stage="cleanup", runtime=runtime)
    cleanup.clean_document(document)
    runtime.save_blocks(job_id, document)

    await update_job(job_id, stage="segmenting", runtime=runtime)
    plan = runtime.build_segment_plan(document)
    plan = await runtime.refine_segment_plan(plan, document)

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
    job = await get_job(job_id, runtime=runtime)
    options = (job or {}).get("options") or {}
    if "is_raw" not in options and _looks_raw(document.meta.get("language")):
        options = {**options, "is_raw": True}

    await update_job(
        job_id,
        options=options,
        detected_meta=_public_meta(document.meta, job_id, runtime=runtime),
        plan=plan,
        stats=stats,
        status="awaiting_review",
        stage="awaiting review",
        error=None,
        runtime=runtime,
    )
    _log_event(
        logging.INFO, "import_job.parsed",
        f"Import job {job_id} parsed {stats['segments']} segments and "
        f"{stats['images']} images.",
        job_system="import", job_id=job_id, segments=stats["segments"],
        images=stats["images"], blocks=stats["blocks"], words=stats["words"],
        quality_score=stats["quality"]["score"],
    )
    await _auto_advance(job_id, runtime=runtime)


# States a batch sibling passes through on its own before it reaches review — while any
# sibling is still in one of these, a `group_series` batch waits before committing the group.
# (awaiting_ocr_confirm is excluded: it needs a human, so it never blocks the rest.)
_PRE_REVIEW = ("receiving", "uploaded", "parsing", "segmenting",
               "ocr_pending", "ocr_running", "ocr_paused")


async def _batch_siblings(batch_id: str, *, runtime) -> list[dict]:
    if not batch_id:
        return []
    rows = await (await _worker_repository(runtime)).batch_siblings(batch_id)
    return [_row_to_job(r) for r in rows]


async def _auto_advance(job_id: int, *, runtime) -> None:
    """Honour ``options.auto_commit`` for folder/batch imports. Without ``group_series`` each
    book commits to its own new novel; with it, once every auto-progressing sibling in the
    batch has reached review, siblings are grouped by detected series and each multi-volume
    group is committed into a single novel (others commit individually)."""
    job = await get_job(job_id, runtime=runtime)
    options = (job or {}).get("options") or {}
    if not options.get("auto_commit"):
        return
    if not options.get("group_series"):
        await update_job(
            job_id, status="committing", stage="auto-committing", runtime=runtime
        )
        return

    siblings = await _batch_siblings(options.get("batch_id"), runtime=runtime)
    if any(s["status"] in _PRE_REVIEW for s in siblings):
        return  # the last straggler to finish parsing will trigger the grouped commit

    ready = [s for s in siblings if s["status"] == "awaiting_review"]
    groups: dict[str, list[dict]] = {}
    for s in ready:
        series = ((s.get("detected_meta") or {}).get("series") or "").strip()
        groups.setdefault(series or f"__single_{s['id']}", []).append(s)

    for key, grp in groups.items():
        ids = [int(s["id"]) for s in grp]
        if key.startswith("__single_") or len(ids) == 1:
            await update_job(
                ids[0], status="committing", stage="auto-committing", runtime=runtime
            )
            continue
        try:
            await runtime.commit_series(ids)
            _log_event(
                logging.INFO, "import_batch.series_committed",
                f"Auto-committed a {len(ids)}-volume series from an import batch.",
                job_system="import", job_ids=ids, volumes=len(ids),
                batch_id=options.get("batch_id"),
            )
        except Exception as e:
            _log_event(
                logging.WARNING, "import_batch.series_commit_failed",
                f"Auto-commit failed for a {len(ids)}-volume import series.",
                job_system="import", job_ids=ids, volumes=len(ids),
                batch_id=options.get("batch_id"), error_type=type(e).__name__,
                error=str(e),
            )
            for jid in ids:
                await fail_job(
                    jid, f"series commit: {type(e).__name__}: {e}", runtime=runtime
                )


async def imports_with_hash(
    file_sha256: str, exclude_job_id: int | None = None, *, runtime
) -> list[dict]:
    """Prior import jobs for the same file bytes (re-import detection). Most-recent first;
    callers surface committed ones as a 'you already imported this' warning."""
    if not file_sha256:
        return []
    rows = await (await _worker_repository(runtime)).duplicate_imports(
        file_sha256, exclude_job_id
    )
    titles = await runtime.novel_titles({
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

async def _gemini_budget_remaining(runtime) -> int:
    return await runtime.gemini_budget_remaining()


async def _enter_ocr_confirm(job_id: int, document, job: dict, *, runtime) -> None:
    """A scanned PDF is expensive, so we estimate the OCR cost and park the job behind a
    confirm gate instead of burning quota unprompted."""
    options = job.get("options") or {}
    pages = document.meta.get("page_count", 0)
    est = runtime.estimate_ocr_cost(
        pages, bool(options.get("gemini_first")), await _gemini_budget_remaining(runtime)
    )
    await update_job(
        job_id,
        status="awaiting_ocr_confirm",
        stage="awaiting OCR confirmation",
        cost_estimate=est,
        detected_meta=_public_meta(document.meta, job_id, runtime=runtime),
        stats={"page_count": pages, "scanned_pages": est["scanned_pages"]},
        error=None,
        runtime=runtime,
    )
    _log_event(
        logging.INFO, "import_job.awaiting_ocr_confirmation",
        f"Import job {job_id} detected a scanned PDF with {pages} pages and is awaiting OCR confirmation.",
        job_system="import", job_id=job_id, pages=pages,
        scanned_pages=est.get("scanned_pages"),
    )


async def do_ocr(job: dict, *, runtime) -> None:
    """ocr_pending → OCR (serialized on the GPU) → finish parse. A budget exhaustion parks
    the job in `ocr_paused`; per-page checkpoints mean it resumes where it left off."""
    job_id = int(job["id"])
    from novelwiki.modules.ai_execution.public import BudgetExhausted
    options = job.get("options") or {}

    async with _OCR_LOCK:
        await update_job(
            job_id, status="ocr_running", stage="OCR in progress", error=None,
            runtime=runtime,
        )

        async def progress_cb(done, total):
            await update_job(
                job_id, progress={"done": done, "total": total, "unit": "pages"},
                runtime=runtime,
            )

        try:
            document = await runtime.parse_pdf_ocr(
                job["original_path"], job_id, options, progress_cb
            )
        except BudgetExhausted:
            await update_job(job_id, status="ocr_paused",
                             stage="paused — Gemini daily budget reached; resumes tomorrow",
                             runtime=runtime)
            _log_event(
                logging.WARNING, "import_job.ocr_paused",
                f"Import job {job_id} paused OCR because the provider budget was exhausted.",
                job_system="import", job_id=job_id, reason="provider_budget_exhausted",
            )
            return

    # CJK scans flow into the translation pipeline as a raw source (text == source language).
    if (document.meta.get("language") or "")[:2] in _CJK:
        await update_job(
            job_id, options={**options, "is_raw": True}, runtime=runtime
        )
    await _finish_parse(job_id, document, runtime=runtime)


async def do_commit(job: dict, *, runtime) -> None:
    """commit_running → write chapters/assets via the scraper persist path → committed.

    ``commit_job`` records completion (novel_id + status='committed') INSIDE its own
    transaction, so this stage is crash-safe: if a restart interrupts a commit, the work
    either fully rolled back (requeued `committing` re-runs clean) or fully landed as
    'committed' (a terminal state, never re-run) — a duplicate novel can't slip through the
    gap. The atomic claim also guarantees only one worker is ever in this stage for a job."""
    job_id = int(job["id"])
    await update_job(job_id, stage="committing", runtime=runtime)
    result = await runtime.commit_job(job)
    _log_event(
        logging.INFO, "import_job.committed",
        f"Import job {job_id} committed to novel {result['novel_id']}.",
        job_system="import", job_id=job_id, novel_id=result["novel_id"],
        chapters_written=result.get("stats", {}).get("chapters_written", 0),
        from_chapter=result.get("stats", {}).get("from_chapter"),
        to_chapter=result.get("stats", {}).get("to_chapter"),
    )


def _public_meta(meta: dict, job_id: int, *, runtime) -> dict:
    """The metadata surfaced to the UI: book fields + a staged cover thumbnail URL."""
    out = {
        "title": meta.get("title"),
        "author": meta.get("author"),
        "language": meta.get("language"),
        "description": meta.get("description"),
        "series": meta.get("series"),
        "series_index": meta.get("series_index"),
        "volume_label": meta.get("volume_label"),
    }
    cover_sha = meta.get("cover_sha")
    assets = meta.get("assets") or {}
    if cover_sha and cover_sha in assets:
        ext = assets[cover_sha].get("ext", "jpg")
        out["cover_sha"] = cover_sha
        out["cover_url"] = runtime.staged_asset_url(job_id, cover_sha, ext)
    return out
