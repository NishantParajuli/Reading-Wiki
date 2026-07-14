from __future__ import annotations

import logging
import re
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from novelwiki.platform.auth import current_user
from novelwiki.kernel.errors import (
    Conflict,
    Forbidden,
    NotFound,
    QuotaExceeded,
    ValidationFailed,
)
from novelwiki.modules.identity.public import Principal
from novelwiki.platform.config import settings
from novelwiki.platform.observability import audit
from novelwiki.platform.observability.logging import log_context, log_event

from ...application import ReadingService
from ...application.migration import ReadingMigrationService

router = APIRouter()
logger = logging.getLogger(__name__)


async def _logged_translation_prefetch(
    service: ReadingMigrationService,
    novel_id: int,
    after_number: float,
    principal: Principal | None,
    request_id: str | None,
) -> None:
    with log_context(
        request_id=request_id, job_system="inline_background",
        job_kind="translation_prefetch", novel_id=novel_id,
        user_id=principal.user_id if principal is not None else None,
        after_chapter=after_number,
    ):
        started = time.monotonic()
        log_event(
            logger, logging.INFO, "background_task.started",
            f"Starting translation prefetch after chapter {after_number} for novel {novel_id}.",
        )
        try:
            await service.prefetch(novel_id, after_number, principal)
        except Exception:
            log_event(
                logger, logging.ERROR, "background_task.failed",
                f"Translation prefetch after chapter {after_number} for novel {novel_id} failed.",
                exc_info=True,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            raise
        else:
            log_event(
                logger, logging.INFO, "background_task.completed",
                f"Translation prefetch after chapter {after_number} for novel {novel_id} completed.",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )


class ProgressUpdate(BaseModel):
    last_chapter: float
    scroll_pct: float = 0


class BookmarkCreate(BaseModel):
    chapter: float
    note: str | None = None


class OverlayUpdate(BaseModel):
    content: str


class ResolveOverlay(BaseModel):
    choice: str
    content: str | None = None


class ContributionAccept(BaseModel):
    content: str | None = None


async def reading_service_dependency() -> ReadingService:
    raise RuntimeError("ReadingService was not wired by the composition root")


async def reading_migration_service_dependency() -> ReadingMigrationService:
    raise RuntimeError("ReadingMigrationService was not wired by the composition root")


def _principal(user: dict) -> Principal:
    return Principal.from_user(
        user,
        {
            "translated_chapters": settings.DEFAULT_QUOTA_TRANSLATED_CHAPTERS,
            "ocr_pages": settings.DEFAULT_QUOTA_OCR_PAGES,
            "codex_builds": settings.DEFAULT_QUOTA_CODEX_BUILDS,
            "tts_chapters": settings.DEFAULT_QUOTA_TTS_CHAPTERS,
        },
    )


def _optional_principal(user: object) -> Principal | None:
    return _principal(user) if isinstance(user, dict) else None


def _translate_access_error(exc: Exception) -> None:
    if isinstance(exc, NotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, Forbidden):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    raise exc


def _translate_migration_error(exc: Exception) -> None:
    if isinstance(exc, NotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, Forbidden):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, Conflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValidationFailed):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, QuotaExceeded):
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    raise exc


_RICH_ASSET_RE = re.compile(
    r"(?P<quote>['\"])/assets/(?P<novel_id>\d+)/(?P<filename>[^'\"?#]+)"
)


def _rewrite_rich_asset_urls(html: str | None, novel_id: int) -> str | None:
    if not html:
        return html

    def replace(match: re.Match) -> str:
        if int(match.group("novel_id")) != int(novel_id):
            return match.group(0)
        return (
            f"{match.group('quote')}/api/assets/novels/{novel_id}/"
            f"{match.group('filename')}"
        )

    return _RICH_ASSET_RE.sub(replace, html)


@router.get("/novels/{novel_id}/chapters")
async def api_list_chapters(
    novel_id: int,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """The table of contents for the reader."""
    try:
        rows = await service.list_chapters(novel_id, _optional_principal(user))
    except (NotFound, Forbidden) as exc:
        _translate_migration_error(exc)
    return [
        {
            "number": row.number,
            "title": row.title,
            "language": row.language,
            "is_translated": row.is_translated,
            "translation_status": row.translation_status,
            "has_content": row.has_content,
            "word_count": row.word_count,
            "kind": row.kind,
            "part_label": row.part_label,
        }
        for row in rows
    ]


@router.get("/novels/{novel_id}/chapter/{number}")
async def api_get_chapter(
    novel_id: int,
    number: float,
    bg_tasks: BackgroundTasks,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Returns one chapter's readable content for the reader, plus prev/next numbers.
    Raw chapters are translated on demand here (and the next few are prefetched in the
    background), so the reader always gets English text — keyed off `translation_status`."""
    principal = _optional_principal(user)
    try:
        result = await service.get_chapter(novel_id, number, principal)
    except (NotFound, Forbidden) as exc:
        _translate_migration_error(exc)
    chapter = result.snapshot
    content = result.content
    rich_html = (
        chapter.raw_html
        if chapter.adapter in ("epub", "pdf") and not chapter.source_is_raw
        else None
    )
    rich_html = _rewrite_rich_asset_urls(rich_html, novel_id)
    base_content = content
    overlay_active = chapter.overlay_base_version is not None
    if overlay_active:
        content = chapter.overlay_content
        rich_html = None
    if result.prefetch_after is not None:
        bg_tasks.add_task(
            _logged_translation_prefetch, service, novel_id, result.prefetch_after,
            principal, audit.get_request_id(),
        )
    can_edit_base = principal is not None and (
        principal.is_admin or result.novel.owner_id == principal.user_id
    )
    return {
        "number": chapter.number,
        "title": chapter.title,
        "content": content,
        "rich_html": rich_html,
        "language": chapter.language,
        "is_translated": result.is_translated,
        "translation_status": result.translation_status,
        "word_count": chapter.word_count,
        "prev": chapter.previous_number,
        "next": chapter.next_number,
        "prev_title": chapter.previous_title,
        "next_title": chapter.next_title,
        "next_is_raw": chapter.next_is_raw,
        "content_version": chapter.content_version,
        "has_original": chapter.has_original,
        "can_edit_base": can_edit_base,
        "is_owner": (
            principal is not None and result.novel.owner_id == principal.user_id
        ),
        "contribution_policy": result.novel.contribution_policy or "manual",
        "overlay": overlay_active,
        "overlay_origin": chapter.overlay_origin if overlay_active else None,
        "overlay_base_version": (
            chapter.overlay_base_version if overlay_active else None
        ),
        "overlay_conflict": chapter.overlay_conflict,
        "base_content": base_content if overlay_active else None,
        "provenance": {
            "adapter": chapter.adapter,
            "imported": chapter.adapter in ("epub", "pdf"),
            "scraped": (
                chapter.adapter is not None and chapter.adapter not in ("epub", "pdf")
            ),
            "translated": bool(result.is_translated),
            "user_edited": chapter.content_version > 1 or overlay_active,
        },
    }


@router.put("/novels/{novel_id}/chapter/{number}/content")
async def api_edit_base_content(
    novel_id: int,
    number: float,
    payload: OverlayUpdate,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Owner/admin: edit the shared base translation directly. Bumps the content version, so
    other readers' overlays of this chapter become conflicts they can resolve."""
    try:
        version = await service.edit_base_content(
            novel_id, number, payload.content, _principal(user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _translate_migration_error(exc)
    return {"status": "success", "content_version": version}


@router.put("/novels/{novel_id}/chapter/{number}/overlay")
async def api_save_overlay(
    novel_id: int,
    number: float,
    payload: OverlayUpdate,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Save the reader's personal translation override for this chapter, forked from the
    current base version. Replaces any existing overlay and clears its conflict flag."""
    try:
        await service.save_overlay(
            novel_id, number, payload.content, _principal(user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _translate_migration_error(exc)
    return {"status": "success"}


@router.delete("/novels/{novel_id}/chapter/{number}/overlay")
async def api_delete_overlay(
    novel_id: int,
    number: float,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Drop the reader's overlay for this chapter and fall back to the shared base."""
    try:
        await service.delete_overlay(novel_id, number, _principal(user))
    except (NotFound, Forbidden) as exc:
        _translate_migration_error(exc)
    return {"status": "success"}


@router.post("/novels/{novel_id}/chapter/{number}/self-translate")
async def api_self_translate(
    novel_id: int,
    number: float,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Translate a raw chapter into the reader's own overlay (counts against their monthly
    translated-chapters quota). Only applies to chapters that have source-language text."""
    try:
        content = await service.self_translate(
            novel_id, number, _principal(user)
        )
    except (NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _translate_migration_error(exc)
    return {"status": "success", "content": content}


@router.post("/novels/{novel_id}/chapter/{number}/resolve")
async def api_resolve_overlay(
    novel_id: int,
    number: float,
    payload: ResolveOverlay,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Resolve a base-vs-overlay conflict: keep the base (drop the overlay), keep mine
    (re-anchor the overlay to the current base), or save a merged result."""
    try:
        await service.resolve_overlay(
            novel_id, number, payload.choice, payload.content, _principal(user)
        )
    except (NotFound, Forbidden, ValidationFailed) as exc:
        _translate_migration_error(exc)
    return {"status": "success"}


@router.post("/novels/{novel_id}/chapter/{number}/contribute")
async def api_contribute(
    novel_id: int,
    number: float,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Offer the reader's overlay back to the novel owner. With contribution_policy='auto'
    and no conflict (the base hasn't moved since the overlay forked) it merges into the base
    immediately; otherwise it lands in the owner's review inbox as a pending contribution."""
    try:
        status, contribution_id = await service.contribute(
            novel_id, number, _principal(user)
        )
    except (NotFound, Forbidden, Conflict) as exc:
        _translate_migration_error(exc)
    return {"status": status, "id": contribution_id}


@router.get("/novels/{novel_id}/contributions")
async def api_list_contributions(
    novel_id: int,
    status: str = "pending",
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Owner/admin inbox of contribute-back offers (defaults to pending)."""
    try:
        return await service.list_contributions(
            novel_id, status, _principal(user)
        )
    except (NotFound, Forbidden) as exc:
        _translate_migration_error(exc)


@router.post("/novels/{novel_id}/contributions/{contribution_id}/accept")
async def api_accept_contribution(
    novel_id: int,
    contribution_id: int,
    payload: ContributionAccept | None = None,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Owner/admin: merge a pending contribution into the shared base. If the shared base
    changed after the contribution was offered, callers must provide resolved content so a
    stale proposal cannot overwrite newer translation work by accident."""
    try:
        await service.accept_contribution(
            novel_id, contribution_id,
            payload.content if payload else None,
            _principal(user),
        )
    except (NotFound, Forbidden, Conflict) as exc:
        _translate_migration_error(exc)
    return {"status": "accepted"}


@router.post("/novels/{novel_id}/contributions/{contribution_id}/reject")
async def api_reject_contribution(
    novel_id: int,
    contribution_id: int,
    user: dict = Depends(current_user),
    service: ReadingMigrationService = Depends(reading_migration_service_dependency),
):
    """Owner/admin: decline a pending contribution (the contributor keeps their overlay)."""
    try:
        await service.reject_contribution(
            novel_id, contribution_id, _principal(user)
        )
    except (NotFound, Forbidden) as exc:
        _translate_migration_error(exc)
    return {"status": "rejected"}


@router.get("/novels/{novel_id}/progress")
async def api_get_progress(
    novel_id: int,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        progress = await service.get_progress(novel_id, _principal(user))
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {
        "last_chapter": progress.last_chapter,
        "max_chapter_read": progress.max_chapter_read,
        "scroll_pct": progress.scroll_pct,
    }


@router.put("/novels/{novel_id}/progress")
async def api_set_progress(
    novel_id: int,
    payload: ProgressUpdate,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        await service.set_progress(
            novel_id, _principal(user), payload.last_chapter, payload.scroll_pct
        )
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {"status": "success"}


@router.get("/novels/{novel_id}/bookmarks")
async def api_list_bookmarks(
    novel_id: int,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        rows = await service.list_bookmarks(novel_id, _principal(user))
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return [
        {
            "id": row.id,
            "chapter": row.chapter,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.post("/novels/{novel_id}/bookmarks")
async def api_add_bookmark(
    novel_id: int,
    payload: BookmarkCreate,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        bookmark_id = await service.add_bookmark(
            novel_id, _principal(user), payload.chapter, payload.note
        )
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {"id": bookmark_id}


@router.delete("/novels/{novel_id}/bookmarks/{bookmark_id}")
async def api_delete_bookmark(
    novel_id: int,
    bookmark_id: int,
    user: dict = Depends(current_user),
    service: ReadingService = Depends(reading_service_dependency),
):
    try:
        await service.delete_bookmark(novel_id, _principal(user), bookmark_id)
    except (NotFound, Forbidden) as exc:
        _translate_access_error(exc)
    return {"status": "success"}
