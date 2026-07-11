"""Batch 9: product-operations + reader-MVP surfaces.

A cohesive set of read-mostly endpoints layered on the existing data model so a signed-in
reader can immediately resume, see what work is running, understand what an action will cost,
and get a spoiler-safe recap:

  - ``GET  /home``                       unified "continue" landing (reading / listening /
                                          active work / recent imports / newest shared novels)
  - ``GET  /activity``                   one feed over the three durable job systems
                                          (generic jobs + import jobs + TTS jobs) for the caller
  - ``GET  /novels/{id}/health``         operator health panel (codex / translation / audio /
                                          source freshness / recent errors)
  - ``GET  /novels/{id}/cost-estimate``  pre-flight estimated units + quota remaining for an
                                          expensive action (never charges — the action does)
  - ``POST /novels/{id}/recap``          spoiler-safe recap, bounded by the SAME trusted
                                          effective ceiling and read-side AI cost gates as ``/ask``

Everything spoiler-sensitive routes through ``require_effective_ceiling`` (never above what the
server has actually served this reader), and the home/activity feeds only ever surface novels the
caller can read.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import novelwiki.modules.identity.public as quota
from novelwiki.modules.catalog.public import can_edit, is_admin, require_readable
from novelwiki.platform.auth import current_user
from novelwiki.platform.config import settings
from novelwiki.modules.work.public import service as jobs_service
from novelwiki.modules.codex.public import CodexRecapApi
from novelwiki.modules.identity.public import Principal
from novelwiki.modules.narration.public import shared_audio_coverage

logger = logging.getLogger(__name__)
router = APIRouter()

async def codex_recap_service_dependency() -> CodexRecapApi:
    raise RuntimeError("CodexRecapService was not wired by the composition root")


async def codex_recap_principal_factory_dependency():
    raise RuntimeError("Codex recap principal factory was not wired by the composition root")

# Terminal states per job system (everything else counts as "active / in progress").
_IMPORT_TERMINAL = {"committed", "failed", "canceled"}
_TTS_ACTIVE = ("queued", "generating")


async def _operational_projections():
    from novelwiki.bootstrap.experience import build_operational_projection_repository
    return await build_operational_projection_repository()


# ── Unified activity feed (generic + import + TTS jobs) ───────────────────────

def _generic_job_row(j: dict) -> dict:
    v = jobs_service.job_view(j)
    active = v["status"] in jobs_service.ACTIVE_STATUSES
    return {
        "source": "job",
        "id": v["id"],
        "kind": v["kind"],
        "novel_id": v["novel_id"],
        "status": v["status"],
        "stage": v["stage"],
        "progress": v["progress"],
        "error": v["error"],
        "attempts": v["attempts"],
        "max_attempts": v["max_attempts"],
        "execution_backend": v["execution_backend"],
        "backend_model": v["backend_model"],
        "backend_fallback_from": v["backend_fallback_from"],
        "plugin_version": v["plugin_version"],
        "cancelable": active,
        "updated_at": v["updated_at"],
        "created_at": v["created_at"],
    }


def _import_job_row(j: dict) -> dict:
    import os
    status = j["status"]
    active = status not in _IMPORT_TERMINAL
    return {
        "source": "import",
        "id": int(j["id"]),
        "kind": "import",
        "novel_id": int(j["novel_id"]) if j.get("novel_id") is not None else None,
        "status": status,
        "stage": j.get("stage"),
        "progress": j.get("progress") or {},
        "error": j.get("error"),
        "filename": os.path.basename(j.get("original_path") or "") or None,
        # Import jobs can be canceled while in-flight; a job awaiting the user's review/OCR
        # confirmation isn't "cancelable work" in the same sense, but the endpoint still allows it.
        "cancelable": active and status not in ("committing",),
        "updated_at": j["updated_at"].isoformat() if j.get("updated_at") else None,
        "created_at": j["created_at"].isoformat() if j.get("created_at") else None,
    }


def _tts_job_row(j: dict) -> dict:
    status = j["status"]
    active = status in _TTS_ACTIVE
    return {
        "source": "tts",
        "id": int(j["id"]),
        "kind": "tts",
        "scope": j.get("scope"),
        "voice_id": j.get("voice_id"),
        "novel_id": int(j["novel_id"]) if j.get("novel_id") is not None else None,
        "status": status,
        "stage": j.get("stage"),
        "progress": j.get("progress") or {},
        "error": j.get("error"),
        "cancelable": active,
        "updated_at": j["updated_at"].isoformat() if j.get("updated_at") else None,
        "created_at": j["created_at"].isoformat() if j.get("created_at") else None,
    }


async def _collect_activity(user: dict, *, active_only: bool, limit: int) -> list[dict]:
    """Merge the caller's jobs from all three durable systems into one normalized, newest-first
    feed. Non-admins only ever see their own jobs (the underlying listers scope by user_id)."""
    admin = is_admin(user)
    scope = None if admin else user["id"]

    generic = await jobs_service.list_jobs(user_id=scope, active_only=active_only, limit=limit)
    import_rows = await _list_import_jobs(scope, active_only=active_only, limit=limit)
    tts_rows = await _list_tts_jobs(scope, active_only=active_only, limit=limit)

    rows = [_generic_job_row(j) for j in generic]
    rows += [_import_job_row(j) for j in import_rows]
    rows += [_tts_job_row(j) for j in tts_rows]

    if active_only:
        rows = [
            r for r in rows
            if r["cancelable"]
            or (r["source"] == "import" and r["status"] not in _IMPORT_TERMINAL)
            or r["status"] in ("awaiting_review", "awaiting_ocr_confirm", "ocr_paused")
        ]

    # Newest activity first; rows without a timestamp sink to the bottom.
    rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return rows[:limit]


async def _list_import_jobs(user_id: int | None, *, active_only: bool, limit: int) -> list[dict]:
    """Import jobs with the active filter applied in SQL before LIMIT.

    ``importer.jobs.list_jobs`` is intentionally a simple newest-first lister; the unified
    activity surface needs active/attention imports even when many newer completed imports exist.
    """
    import json

    rows = await (await _operational_projections()).import_activity(
        user_id, active_only, _IMPORT_TERMINAL, max(1, min(int(limit), 200))
    )
    out = []
    for r in rows:
        d = dict(r)
        p = d.get("progress")
        if isinstance(p, str):
            try:
                d["progress"] = json.loads(p)
            except Exception:
                d["progress"] = {}
        out.append(d)
    return out


async def _list_tts_jobs(user_id: int | None, *, active_only: bool, limit: int) -> list[dict]:
    rows = await (await _operational_projections()).tts_activity(
        user_id, active_only, _TTS_ACTIVE, max(1, min(int(limit), 200))
    )
    out = []
    for r in rows:
        d = dict(r)
        p = d.get("progress")
        if isinstance(p, str):
            import json
            try:
                d["progress"] = json.loads(p)
            except Exception:
                d["progress"] = {}
        out.append(d)
    return out


@router.get("/activity")
async def api_activity(status: str = "active", limit: int = 100, user: dict = Depends(current_user)):
    """The caller's background work across the generic, import, and TTS job systems in one feed.

    ``status=active`` (default) shows only in-flight / needs-attention work; ``status=all`` includes
    finished and failed jobs so the user can see recent outcomes. Non-admins only ever see their own
    jobs. The frontend dispatches Cancel to the right endpoint using each row's ``source``.
    """
    active_only = status != "all"
    rows = await _collect_activity(user, active_only=active_only, limit=max(1, min(int(limit), 200)))
    return {"jobs": rows}


# ── Unified "continue" home ───────────────────────────────────────────────────
# The readable predicate below mirrors ``access.can_read``: a novel is readable if it's
# global/public, owned by the caller, or the caller is an admin.

@router.get("/home")
async def api_home(user: dict = Depends(current_user)):
    """The first screen after login: resume reading/listening, see active work, recent imports,
    and the newest shared novels. Every novel surfaced here is one the caller can actually read
    (shared, owned, or admin-readable) — never a private novel they've lost access to."""
    admin = is_admin(user)
    cont_rows, updated_rows, newest_rows = await (
        await _operational_projections()
    ).home_rows(int(user["id"]), admin)

    def _cont(r):
        max_ch = float(r["max_chapter"]) if r["max_chapter"] is not None else None
        read = float(r["max_chapter_read"]) if r["max_chapter_read"] is not None else None
        pct = 0
        if max_ch and max_ch > 0 and read is not None:
            pct = round(min(100.0, (read / max_ch) * 100))
        new_chapters = 0
        if max_ch is not None and read is not None:
            new_chapters = max(0, int(round(max_ch - read)))
        return {
            "id": int(r["id"]),
            "title": r["title"],
            "author": r["author"],
            "shelf": r["shelf"],
            "cover_url": _rewrite(r["cover_url"], int(r["id"])),
            "visibility": r["visibility"],
            "last_chapter": float(r["last_chapter"]) if r["last_chapter"] is not None else None,
            "resume_chapter_title": r["resume_chapter_title"],
            "last_read_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "max_chapter_read": read,
            "scroll_pct": float(r["scroll_pct"]) if r["scroll_pct"] is not None else 0,
            "max_chapter": max_ch,
            "pct_read": pct,
            "new_chapters": new_chapters,
            "audio_chapters": int(r["audio_chapters"] or 0),
        }

    continue_reading = [_cont(r) for r in cont_rows]

    updated_in_library = [
        {
            "id": int(r["id"]),
            "title": r["title"],
            "author": r["author"],
            "cover_url": _rewrite(r["cover_url"], int(r["id"])),
            "max_chapter_read": float(r["max_chapter_read"]) if r["max_chapter_read"] is not None else None,
            "max_chapter": float(r["max_chapter"]) if r["max_chapter"] is not None else None,
            "new_chapters": int(r["new_chapters"] or 0),
            "source_updated_at": r["source_updated_at"].isoformat() if r["source_updated_at"] else None,
        }
        for r in updated_rows
        if int(r["new_chapters"] or 0) > 0
    ]
    # "Continue listening" is the subset with shared narration available — honest given we don't
    # track a separate audio playback position, but we do know where they're reading and what's narrated.
    continue_listening = [c for c in continue_reading if c["audio_chapters"] > 0]

    activity = await _collect_activity(user, active_only=True, limit=8)
    recent_imports = await _recent_imports(user, limit=5)

    newest = [
        {"id": int(r["id"]), "title": r["title"], "author": r["author"],
         "cover_url": _rewrite(r["cover_url"], int(r["id"])), "visibility": r["visibility"],
         "owner_username": r["owner_username"], "chapter_count": int(r["chapter_count"] or 0),
         "has_codex": bool(r["codex_enabled"]), "has_audio": bool(r["has_audio"])}
        for r in newest_rows
    ]

    return {
        "continue_reading": continue_reading,
        "continue_listening": continue_listening,
        "updated_in_library": updated_in_library,
        "active_jobs": activity,
        "recent_imports": recent_imports,
        "newest": newest,
    }


async def _recent_imports(user: dict, *, limit: int) -> list[dict]:
    from novelwiki.modules.acquisition.public import list_import_jobs
    import os
    scope = None if is_admin(user) else user["id"]
    rows = await list_import_jobs(user_id=scope, limit=limit)
    return [
        {
            "id": int(j["id"]),
            "novel_id": int(j["novel_id"]) if j.get("novel_id") is not None else None,
            "status": j["status"],
            "stage": j.get("stage"),
            "filename": os.path.basename(j.get("original_path") or "") or None,
            "updated_at": j["updated_at"].isoformat() if j.get("updated_at") else None,
        }
        for j in rows[:limit]
    ]


def _rewrite(cover_url, novel_id):
    """Map historical public asset URLs onto the access-controlled asset endpoint."""
    if not cover_url:
        return cover_url
    match = re.match(r"^/assets/(?P<novel_id>\d+)/(?P<filename>[^/?#]+)$", cover_url)
    if not match or int(match.group("novel_id")) != int(novel_id):
        return cover_url
    return f"/api/assets/novels/{novel_id}/{match.group('filename')}"


# ── Novel health panel ────────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/health")
async def api_novel_health(novel_id: int, voice_id: str | None = None,
                           user: dict = Depends(current_user)):
    """Operator-facing pipeline health for a novel: codex coverage, untranslated raw chapters,
    missing narration for a voice, source freshness, and (for editors) recent pipeline errors.
    Readable by anyone who can read the novel; error detail is editor-only."""
    novel = await require_readable(novel_id, user)
    editor = can_edit(novel, user)
    voice = (voice_id or "").strip()

    metrics, error_rows = await (
        await _operational_projections()
    ).novel_health(novel_id, editor)
    total_chapters = int(metrics["total_chapters"] or 0)
    book_max = metrics["book_max"]
    entities_count = int(metrics["entities_count"] or 0)
    codex_max = metrics["codex_max"]
    untranslated = int(metrics["untranslated"] or 0)
    source_last_scraped = metrics["source_last_scraped"]
    recent_errors = [
        {"kind": row["kind"], "error": (row["error"] or "")[:200],
         "at": row["updated_at"].isoformat() if row["updated_at"] else None}
        for row in error_rows
    ]

    book_max_f = float(book_max) if book_max is not None else None
    codex_max_f = float(codex_max) if codex_max is not None else None
    codex_enabled = bool(novel.get("codex_enabled")) if "codex_enabled" in novel else None
    if codex_enabled is None:
        codex_enabled = bool(metrics["codex_enabled"])

    # Codex is "missing" if enabled but nothing extracted; "stale" if extraction lags the book.
    codex_missing = codex_enabled and entities_count == 0
    codex_stale = bool(codex_enabled and codex_max_f is not None and book_max_f is not None
                       and codex_max_f < book_max_f)
    audio = await shared_audio_coverage(novel_id, [voice] if voice else None)

    return {
        "total_chapters": total_chapters,
        "book_max_chapter": book_max_f,
        "codex": {
            "enabled": codex_enabled,
            "entities": entities_count,
            "coverage_chapter": codex_max_f,
            "missing": codex_missing,
            "stale": codex_stale,
        },
        "untranslated_raw_chapters": untranslated,
        "audio": {
            "voice_id": voice or None,
            "prose_chapters": audio["prose_chapters"],
            "have": audio["chapters_with_any_audio"],
            "chapters_with_any_audio": audio["chapters_with_any_audio"],
            "missing": audio["missing_any"],
            "missing_any": audio["missing_any"],
            "voices": audio["voices"],
        },
        "source_last_scraped": source_last_scraped.isoformat() if source_last_scraped else None,
        "recent_errors": recent_errors,
        "is_editor": editor,
    }


# ── Cost estimate (pre-flight, never charges) ─────────────────────────────────

_ESTIMATE_KIND = {
    "codex_build": "codex_builds",
    "translate": "translated_chapters",
    "audiobook": "tts_chapters",
}


@router.get("/novels/{novel_id}/cost-estimate")
async def api_cost_estimate(novel_id: int, action: str,
                            from_chapter: float | None = None, to_chapter: float | None = None,
                            force: bool = False, voice_id: str | None = None,
                            user: dict = Depends(current_user)):
    """Estimate the units an expensive action would consume and the caller's remaining quota,
    WITHOUT charging or scheduling anything. Drives the pre-action confirmation UI so a user sees
    exactly what a codex build, a batch translation, or a whole-book narration will cost first."""
    await require_readable(novel_id, user)
    if action not in _ESTIMATE_KIND:
        raise HTTPException(status_code=422, detail=f"Unknown action '{action}'.")
    kind = _ESTIMATE_KIND[action]

    capped = False
    if action == "codex_build":
        units = 1
    elif action == "translate":
        units = await (await _operational_projections()).translation_units(
            novel_id, from_chapter, to_chapter, force
        )
    else:  # audiobook
        voice = (voice_id or settings.TTS_DEFAULT_VOICE or "").strip()
        if not voice:
            units = 0
        else:
            missing = await (await _operational_projections()).audiobook_missing(
                novel_id, from_chapter, to_chapter, voice
            )
            cap = settings.TTS_MAX_BATCH_CHAPTERS
            capped = missing > cap
            units = min(missing, cap)

    remaining = await quota.remaining(user, kind)   # None → unlimited (admin)
    limits = None if quota.is_exempt(user) else _quota_limit(user, kind)
    allowed = quota.spend_allowed(user) and (remaining is None or remaining >= units)

    return {
        "action": action,
        "quota_kind": kind,
        "estimated_units": units,
        "capped": capped,
        "remaining": remaining,
        "limit": limits,
        "unlimited": quota.is_exempt(user),
        "spend_allowed": quota.spend_allowed(user),
        "allowed": allowed,
    }


def _quota_limit(user: dict, kind: str) -> int:
    from novelwiki.modules.identity.public import quota_limits
    return quota_limits(user)[kind]


# ── No-spoiler recap ──────────────────────────────────────────────────────────

class RecapRequest(BaseModel):
    ceiling: float | None = None


@router.post("/novels/{novel_id}/recap")
async def api_recap(
    novel_id: int,
    req: RecapRequest,
    user: dict = Depends(current_user),
    service: CodexRecapApi = Depends(codex_recap_service_dependency),
    principal_factory=Depends(codex_recap_principal_factory_dependency),
):
    """Spoiler-safe "story so far" recap, bounded by the same trusted effective ceiling as codex/ask.

    It is a canonical question run through the agentic Q&A orchestrator, so it inherits the read-side
    AI cost controls (verified-email gate, hourly cap, concurrency slot) and grounding/citations. A
    cached recap for this (novel, ceiling) is served free; a cache miss must clear the gates first.
    The model is never given evidence above the effective ceiling, so it cannot recap unread chapters.
    """
    try:
        principal: Principal = principal_factory(user)
        return await service.recap(novel_id, req.ceiling, principal)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recap generation error: {e}")
        raise HTTPException(status_code=502, detail="The AI service failed to build a recap. Please try again.")
