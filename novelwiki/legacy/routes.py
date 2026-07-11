import logging
import json
import os
import re
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Request, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.deps import current_user, require_admin
from novelwiki.auth.access import require_readable, require_editable, can_edit, require_effective_ceiling
from novelwiki.auth.users import self_user_with_capabilities, public_user, valid_username, normalize_username
from novelwiki import quota, ai_limits
from novelwiki.jobs import service as jobs_service
from novelwiki.ai_backend.policy import resolve_backend
from novelwiki.ai_backend.types import Workload
from novelwiki.scraper.runner import set_source_offset
from novelwiki.scraper.adapters import list_adapters
from novelwiki.scraper.safe_fetch import SafeFetchError, validate_source_start_url
from novelwiki.ingest.link import merge_entities
from novelwiki.translate.translate import (
    translate_chapter, prefetch_translations, seed_glossary_from_entities,
    translate_raw_text,
)
from novelwiki.retrieval.bm25 import get_bm25_manager
from novelwiki.retrieval.tools import (
    resolve_entity, get_entity_profile, get_relationships, get_timeline,
    list_entities, get_identity_links
)
from novelwiki.agent.orchestrator import (
    answer_question, compute_query_hash, get_cached_answer, build_citations,
)
from novelwiki.agent.llm_client import call_chat_completion
from novelwiki.agent.prompts import WIKI_PROFILE_SYNTHESIS_SYSTEM, WIKI_PROFILE_SYNTHESIS_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

_OLD_NOVEL_ASSET_RE = re.compile(r"^/assets/(?P<novel_id>\d+)/(?P<filename>[^/?#]+)$")
_RICH_ASSET_RE = re.compile(r"(?P<quote>['\"])/assets/(?P<novel_id>\d+)/(?P<filename>[^'\"?#]+)")
_ASSET_FILENAME_RE = re.compile(r"^(?P<sha>[a-fA-F0-9]{64})\.(?P<ext>[A-Za-z0-9]+)$")

# Shelves a novel can sit on. The shelf is *per-user reading status* (lives in
# library_entries) — one reader's "reading" is another's "completed".
SHELVES = {"to_read", "reading", "completed"}

# Status tags describe the *novel itself* (not a reader's progress) and are therefore
# owner/admin-controlled metadata stored on the novel. Two of the groups are mutually
# exclusive ("radio" — at most one may be set); the rest are free "checkbox" genres.
STATUS_TAG_RADIO_GROUPS = {
    "status":      ["ongoing", "finished", "hiatus"],            # publication status
    "translation": ["translation_ongoing", "translation_completed"],
}
RADIO_TAGS = {t for grp in STATUS_TAG_RADIO_GROUPS.values() for t in grp}
GENRE_TAGS = {
    "action", "adventure", "romance", "fantasy", "sci_fi", "comedy",
    "drama", "horror", "mystery", "slice_of_life",
}
STATUS_TAGS = RADIO_TAGS | GENRE_TAGS   # every tag a novel may legitimately carry


def _clean_status_tags(raw: list[str] | None) -> list[str]:
    """Whitelist + de-dupe novel status tags and enforce one-per-radio-group.
    Raises 422 if a single update sets two mutually-exclusive tags from one group."""
    from novelwiki.kernel.errors import ValidationFailed
    from novelwiki.modules.catalog.domain.tags import clean_status_tags

    try:
        return clean_status_tags(raw)
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _translation_type(has_raw, has_eng) -> str | None:
    """Auto-derived from a novel's sources: English source(s) read as-is = 'translated',
    raw source(s) we translate = 'raws', a mix = 'raws+translated'. None if no sources."""
    if has_raw and has_eng:
        return "raws+translated"
    if has_raw:
        return "raws"
    if has_eng:
        return "translated"
    return None


def _rewrite_asset_url(url: str | None, novel_id: int | None = None) -> str | None:
    if not url:
        return url
    match = _OLD_NOVEL_ASSET_RE.match(url)
    if not match:
        return url
    matched_novel_id = int(match.group("novel_id"))
    if novel_id is not None and matched_novel_id != int(novel_id):
        return url
    return f"/api/assets/novels/{matched_novel_id}/{match.group('filename')}"


def _rewrite_rich_asset_urls(html: str | None, novel_id: int) -> str | None:
    if not html:
        return html

    def repl(match: re.Match) -> str:
        matched_novel_id = int(match.group("novel_id"))
        if matched_novel_id != int(novel_id):
            return match.group(0)
        return f"{match.group('quote')}/api/assets/novels/{matched_novel_id}/{match.group('filename')}"

    return _RICH_ASSET_RE.sub(repl, html)


async def _validated_scraper_start_url(start_url: str) -> str:
    try:
        return await validate_source_start_url(start_url)
    except SafeFetchError as e:
        raise HTTPException(status_code=422, detail=f"Unsafe source URL: {e}")


async def _read_upload_file_limited(file, max_bytes: int, too_large_detail: str) -> bytes:
    """Read an UploadFile-like object in chunks, rejecting as soon as it crosses max_bytes."""
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail=too_large_detail)
    return bytes(data)


# ── API Models ────────────────────────────────────────────────────────────

class SourceCreate(BaseModel):
    adapter: str
    start_url: str
    language: str = "en"
    is_raw: bool = False
    chapter_offset: float = 0
    label: str | None = None
    config: dict | None = None

class SourceUpdate(BaseModel):
    chapter_offset: float | None = None
    start_url: str | None = None
    label: str | None = None
    language: str | None = None
    is_raw: bool | None = None

class NovelCreate(BaseModel):
    title: str
    author: str | None = None
    description: str | None = None
    cover_url: str | None = None
    original_language: str = "en"
    codex_enabled: bool = False
    source: SourceCreate | None = None  # optional first source

class NovelUpdate(BaseModel):
    title: str | None = None
    author: str | None = None
    description: str | None = None
    cover_url: str | None = None
    codex_enabled: bool | None = None
    shelf: str | None = None          # to_read|reading|completed|"" (empty string clears the shelf)
    status_tags: list[str] | None = None
    contribution_policy: str | None = None   # manual|auto: how contribute-back offers merge (owner/admin)

class VisibilityUpdate(BaseModel):
    visibility: str          # private|public|global

class ProfileUpdate(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    username: str | None = None
    prefs: dict | None = None

class OverlayUpdate(BaseModel):
    content: str

class ResolveOverlay(BaseModel):
    choice: str                       # base|mine|merge
    content: str | None = None        # required when choice == 'merge'

class ContributionAccept(BaseModel):
    content: str | None = None        # optional resolved text when accepting a conflicted contribution

class ContributionPolicy(BaseModel):
    contribution_policy: str          # manual|auto

class TagSuggestion(BaseModel):
    tags: list[str]                   # full proposed status_tags set
    note: str | None = None

class ProgressUpdate(BaseModel):
    last_chapter: float
    scroll_pct: float = 0

class BookmarkCreate(BaseModel):
    chapter: float
    note: str | None = None

class AskRequest(BaseModel):
    question: str
    ceiling: float

class ScrapeTrigger(BaseModel):
    force: bool = False
    max_chapters: int | None = None
    source_id: int | None = None  # scrape one source; omit to scrape all of the novel's sources

class TranslateTrigger(BaseModel):
    from_chapter: float | None = None
    to_chapter: float | None = None
    force: bool = False
    seed_from_codex: bool = False
    ai_backend: Literal["auto", "api", "agy"] = "auto"

class GlossaryUpsert(BaseModel):
    source_term: str
    translation: str
    term_type: str | None = None
    notes: str | None = None
    locked: bool = False

class CodexBuild(BaseModel):
    force: bool = False
    from_chapter: float | None = None
    to_chapter: float | None = None
    ai_backend: Literal["auto", "api", "agy"] = "auto"

class MergePayload(BaseModel):
    keep_id: int
    drop_id: int

class Citation(BaseModel):
    kind: str
    id: int
    chapter: float
    snippet: str

class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    evidence_ids: dict
    requested_ceiling: float | None = None
    allowed_ceiling: float | None = None
    effective_ceiling: float | None = None
    ceiling_clamped: bool = False


# ── Adapters ──────────────────────────────────────────────────────────────

async def api_adapters():
    """The scraping techniques available for the Add-Source dropdown."""
    from novelwiki.bootstrap.acquisition import build_adapter_catalog_query
    from novelwiki.modules.acquisition.adapters.inbound.http import api_adapters as handler

    return await handler(build_adapter_catalog_query())


# ── Library / Novels ──────────────────────────────────────────────────────

@router.get("/novels")
async def api_list_novels(user: dict = Depends(current_user)):
    """The caller's library grid: only novels they own or have explicitly added to their
    library. Shared (global/public) novels are *not* in the library until added from Discover.
    Shelf is per-user; status tags are the novel's own (owner/admin-curated) metadata."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id, n.title, n.author, n.cover_url, n.description, n.codex_enabled,
                   n.visibility, n.owner_id,
                   le.shelf AS shelf,
                   n.status_tags AS status_tags,
                   COUNT(c.number) AS chapter_count,
                   MIN(c.number) AS min_chapter, MAX(c.number) AS max_chapter,
                   p.last_chapter, p.max_chapter_read, p.updated_at AS last_read_at,
                   (SELECT bool_or(s.is_raw)     FROM sources s WHERE s.novel_id = n.id) AS has_raw,
                   (SELECT bool_or(NOT s.is_raw)  FROM sources s WHERE s.novel_id = n.id) AS has_eng,
                   (SELECT MAX(s.last_scraped_at) FROM sources s WHERE s.novel_id = n.id) AS source_updated_at
            FROM novels n
            LEFT JOIN library_entries le ON le.novel_id = n.id AND le.user_id = $1
            LEFT JOIN reading_progress p ON p.novel_id = n.id AND p.user_id = $1
            LEFT JOIN chapters c ON c.novel_id = n.id
            WHERE le.id IS NOT NULL OR n.owner_id = $1
            GROUP BY n.id, le.shelf, p.last_chapter, p.max_chapter_read, p.updated_at
            ORDER BY n.updated_at DESC NULLS LAST, n.id DESC;
            """,
            user["id"],
        )
    return [
        {
            "id": int(r["id"]),
            "title": r["title"],
            "author": r["author"],
            "cover_url": _rewrite_asset_url(r["cover_url"], int(r["id"])),
            "description": r["description"],
            "codex_enabled": r["codex_enabled"],
            "visibility": r["visibility"],
            "is_owner": r["owner_id"] == user["id"],
            "can_edit": r["owner_id"] == user["id"] or user.get("role") == "admin",
            "shelf": r["shelf"],
            "status_tags": list(r["status_tags"] or []),
            "translation_type": _translation_type(r["has_raw"], r["has_eng"]),
            "chapter_count": int(r["chapter_count"] or 0),
            "min_chapter": float(r["min_chapter"]) if r["min_chapter"] is not None else None,
            "max_chapter": float(r["max_chapter"]) if r["max_chapter"] is not None else None,
            "last_chapter": float(r["last_chapter"]) if r["last_chapter"] is not None else None,
            "max_chapter_read": float(r["max_chapter_read"]) if r["max_chapter_read"] is not None else None,
            # Sort keys for the Library ("Recently read" / "Recently updated") + "n new" chips.
            "last_read_at": r["last_read_at"].isoformat() if r["last_read_at"] else None,
            "source_updated_at": r["source_updated_at"].isoformat() if r["source_updated_at"] else None,
            "new_chapters": (
                max(0, int(round(float(r["max_chapter"]) - float(r["max_chapter_read"]))))
                if r["max_chapter"] is not None and r["max_chapter_read"] is not None else 0
            ),
        }
        for r in rows
    ]


async def api_create_novel(payload: NovelCreate, user: dict = Depends(current_user)):
    """Create a novel (owned by the caller, private by default) and optionally its first source."""
    from novelwiki.bootstrap.catalog import build_catalog_migration_service
    from novelwiki.modules.catalog.adapters.inbound.http import api_create_novel as handler

    return await handler(
        payload, user=user, service=await build_catalog_migration_service()
    )


@router.get("/novels/{novel_id}")
async def api_get_novel(novel_id: int, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        novel = await conn.fetchrow("SELECT * FROM novels WHERE id = $1;", novel_id)
        if not novel:
            raise HTTPException(status_code=404, detail="Novel not found.")
        span = await conn.fetchrow(
            "SELECT COUNT(*) AS count, MIN(number) AS min, MAX(number) AS max FROM chapters WHERE novel_id = $1;",
            novel_id,
        )
        sources = await conn.fetch(
            """
            SELECT id, adapter, start_url, language, is_raw, chapter_offset, label, last_scraped_at
            FROM sources WHERE novel_id = $1 ORDER BY id ASC;
            """,
            novel_id,
        )
        progress = await conn.fetchrow(
            "SELECT * FROM reading_progress WHERE novel_id = $1 AND user_id = $2;", novel_id, user["id"]
        )
        entry = await conn.fetchrow(
            "SELECT shelf FROM library_entries WHERE novel_id = $1 AND user_id = $2;",
            novel_id, user["id"],
        )
        # Provenance signals (see the `provenance` block below). One cheap query each.
        prov_translated = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM chapters WHERE novel_id = $1 "
            "AND (is_translated = TRUE OR (original_text IS NOT NULL AND translation_status = 'done')));",
            novel_id,
        )
        prov_edited = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM chapters WHERE novel_id = $1 AND content_version > 1) "
            "OR EXISTS (SELECT 1 FROM chapter_overlays WHERE novel_id = $1);",
            novel_id,
        )
        prov_ocr = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM import_jobs WHERE novel_id = $1 AND cost_estimate ? 'pages');",
            novel_id,
        )
        prov_approved = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM contributions WHERE novel_id = $1 AND status = 'accepted');",
            novel_id,
        )
    has_raw = any(s["is_raw"] for s in sources) if sources else None
    has_eng = any(not s["is_raw"] for s in sources) if sources else None
    # File-import sources use the epub/pdf adapters; anything else is a web scraper.
    _imported = any(s["adapter"] in ("epub", "pdf") for s in sources)
    _scraped = any(s["adapter"] not in ("epub", "pdf") for s in sources)
    provenance = {
        "scraped": _scraped,
        "imported": _imported,
        "ocr": bool(prov_ocr),
        "translated": bool(prov_translated),
        "user_edited": bool(prov_edited),
        "owner_approved": bool(prov_approved),
        "adapters": sorted({s["adapter"] for s in sources}),
    }
    return {
        "id": int(novel["id"]),
        "title": novel["title"],
        "author": novel["author"],
        "description": novel["description"],
        "cover_url": _rewrite_asset_url(novel["cover_url"], novel_id),
        "original_language": novel["original_language"],
        "codex_enabled": novel["codex_enabled"],
        "visibility": novel["visibility"],
        "is_owner": novel["owner_id"] == user["id"],
        "can_edit": novel["owner_id"] == user["id"] or user.get("role") == "admin",
        # A reader who can't edit but can see a shared (public/global) novel may suggest tags.
        "can_suggest_tags": not (novel["owner_id"] == user["id"] or user.get("role") == "admin")
                            and novel["visibility"] in ("public", "global"),
        "contribution_policy": novel["contribution_policy"],
        "shelf": entry["shelf"] if entry else None,
        "status_tags": list(novel["status_tags"] or []),
        "translation_type": _translation_type(has_raw, has_eng),
        "provenance": provenance,
        "chapter_count": int(span["count"]),
        "min_chapter": float(span["min"]) if span["min"] is not None else None,
        "max_chapter": float(span["max"]) if span["max"] is not None else None,
        "sources": [
            {
                "id": int(s["id"]), "adapter": s["adapter"], "start_url": s["start_url"],
                "language": s["language"], "is_raw": s["is_raw"],
                "chapter_offset": float(s["chapter_offset"] or 0), "label": s["label"],
                "last_scraped_at": s["last_scraped_at"].isoformat() if s["last_scraped_at"] else None,
            }
            for s in sources
        ],
        "progress": {
            "last_chapter": float(progress["last_chapter"]) if progress and progress["last_chapter"] is not None else None,
            "max_chapter_read": float(progress["max_chapter_read"]) if progress and progress["max_chapter_read"] is not None else None,
            "scroll_pct": float(progress["scroll_pct"]) if progress and progress["scroll_pct"] is not None else 0,
        },
    }


async def api_update_novel(novel_id: int, payload: NovelUpdate, user: dict):
    from novelwiki.kernel.errors import Forbidden, NotFound, ValidationFailed
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            status = await (await _catalog_service_compat(conn)).update_novel(
                novel_id,
                Principal.from_user(user),
                payload.model_dump(exclude_unset=True),
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Forbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValidationFailed as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": status}


async def api_upload_novel_cover(novel_id: int, file: UploadFile = File(...), user: dict = Depends(current_user)):
    """Upload a cover image and return an authenticated novel asset URL."""
    from novelwiki.bootstrap.catalog import build_catalog_migration_service
    from novelwiki.modules.catalog.adapters.inbound.http import api_upload_novel_cover as handler

    return await handler(
        novel_id, file, user=user, service=await build_catalog_migration_service()
    )


async def api_delete_novel(novel_id: int, user: dict = Depends(current_user)):
    from novelwiki.bootstrap.catalog import build_catalog_migration_service
    from novelwiki.modules.catalog.adapters.inbound.http import api_delete_novel as handler

    return await handler(
        novel_id, user=user, service=await build_catalog_migration_service()
    )


# ── Visibility, discovery & personal library ────────────────────────────────

async def api_set_visibility(novel_id: int, payload: VisibilityUpdate, user: dict):
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        visibility = await (await _catalog_service_compat(conn)).set_visibility(
            novel_id, Principal.from_user(user), payload.visibility
        )
    return {"status": "success", "visibility": visibility}


@router.get("/discover")
async def api_discover(user: dict = Depends(current_user), q: str | None = None,
                       language: str | None = None, tag: str | None = None,
                       translation: str | None = None, has_codex: bool | None = None,
                       has_audio: bool | None = None, freshness: str | None = None,
                       sort: str = "recent", offset: int = 0, limit: int = 60):
    """Browse the shared library — Global + Public novels the caller hasn't added yet — with
    optional filters. `translation` is the derived translation_type (translated|raws|raws+translated);
    `tag` matches any of a novel's owner-curated status tags, and `freshness` is fresh_7d |
    fresh_30d | stale_30d | never_scraped. `sort` is recent | fresh | title. Paginated via
    offset/limit (max 100); returns ``{items, total, offset, limit}``."""
    # Reusable per-novel derivation subqueries (kept out of the GROUP BY, evaluated per row).
    has_raw_sq = "EXISTS (SELECT 1 FROM sources s WHERE s.novel_id = n.id AND s.is_raw)"
    has_eng_sq = "EXISTS (SELECT 1 FROM sources s WHERE s.novel_id = n.id AND NOT s.is_raw)"
    has_audio_sq = (
        "EXISTS (SELECT 1 FROM chapter_audio a "
        "JOIN chapters c ON c.novel_id = a.novel_id "
        "AND c.number = a.chapter AND c.content_version = a.content_version "
        "WHERE a.novel_id = n.id AND a.user_id IS NULL "
        "AND (c.kind IS NULL OR c.kind = 'chapter'))"
    )
    freshness_sq = "(SELECT MAX(s.last_scraped_at) FROM sources s WHERE s.novel_id = n.id)"

    conds = [
        "n.visibility IN ('global', 'public')",
        "n.owner_id IS DISTINCT FROM $1",
        "le.id IS NULL",
    ]
    args: list = [user["id"]]

    def _p(v):
        args.append(v)
        return f"${len(args)}"

    if q:
        conds.append(f"n.title ILIKE '%' || {_p(q)} || '%'")
    if language:
        conds.append(f"n.original_language = {_p(language)}")
    if tag:
        conds.append(f"{_p(tag)} = ANY(n.status_tags)")
    if translation == "translated":
        conds.append(f"({has_eng_sq} AND NOT {has_raw_sq})")
    elif translation == "raws":
        conds.append(f"({has_raw_sq} AND NOT {has_eng_sq})")
    elif translation in ("raws+translated", "both"):
        conds.append(f"({has_raw_sq} AND {has_eng_sq})")
    if has_codex:
        conds.append("n.codex_enabled = TRUE")
    if has_audio:
        conds.append(has_audio_sq)
    if freshness == "fresh_7d":
        conds.append(f"{freshness_sq} >= now() - interval '7 days'")
    elif freshness == "fresh_30d":
        conds.append(f"{freshness_sq} >= now() - interval '30 days'")
    elif freshness == "stale_30d":
        conds.append(f"{freshness_sq} < now() - interval '30 days'")
    elif freshness == "never_scraped":
        conds.append("NOT EXISTS (SELECT 1 FROM sources s WHERE s.novel_id = n.id AND s.last_scraped_at IS NOT NULL)")

    order = {
        "fresh": f"{freshness_sq} DESC NULLS LAST, n.id DESC",
        "title": "n.title ASC",
        "recent": "(n.visibility = 'global') DESC, n.updated_at DESC NULLS LAST, n.id DESC",
    }.get(sort, "(n.visibility = 'global') DESC, n.updated_at DESC NULLS LAST, n.id DESC")

    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 100))
    args.append(limit)
    limit_p = f"${len(args)}"
    args.append(offset)
    offset_p = f"${len(args)}"

    sql = f"""
        SELECT n.id, n.title, n.author, n.cover_url, n.description, n.visibility,
               n.original_language, n.codex_enabled, n.status_tags,
               u.username AS owner_username,
               (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id) AS chapter_count,
               {has_raw_sq} AS has_raw, {has_eng_sq} AS has_eng, {has_audio_sq} AS has_audio,
               {freshness_sq} AS last_scraped_at,
               COUNT(*) OVER () AS total_count
        FROM novels n
        LEFT JOIN users u ON u.id = n.owner_id
        LEFT JOIN library_entries le ON le.novel_id = n.id AND le.user_id = $1
        WHERE {' AND '.join(conds)}
        ORDER BY {order}
        LIMIT {limit_p} OFFSET {offset_p};
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    total = int(rows[0]["total_count"]) if rows else 0
    items = [
        {"id": int(r["id"]), "title": r["title"], "author": r["author"],
         "cover_url": _rewrite_asset_url(r["cover_url"], int(r["id"])),
         "description": r["description"], "visibility": r["visibility"], "owner_username": r["owner_username"],
         "language": r["original_language"], "status_tags": list(r["status_tags"] or []),
         "translation_type": _translation_type(r["has_raw"], r["has_eng"]),
         "has_codex": bool(r["codex_enabled"]), "has_audio": bool(r["has_audio"]),
         "last_scraped_at": r["last_scraped_at"].isoformat() if r["last_scraped_at"] else None,
         "chapter_count": int(r["chapter_count"] or 0)}
        for r in rows
    ]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


async def _catalog_service_compat(conn):
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService

    return CatalogAccessService(PostgresCatalogRepository(conn))


async def api_add_to_library(novel_id: int, user: dict):
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await (await _catalog_service_compat(conn)).add_to_library(
            novel_id, Principal.from_user(user)
        )
    return {"status": "success"}


async def api_remove_from_library(novel_id: int, user: dict):
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await (await _catalog_service_compat(conn)).remove_from_library(
            novel_id, Principal.from_user(user)
        )
    return {"status": "success"}


async def api_my_usage(user: dict):
    """Compatibility callable; HTTP registration belongs to Identity."""
    return await quota.usage_and_limits(user)


# ── Profiles & account (Phase 3) ────────────────────────────────────────────

@router.get("/users/{username}")
async def api_user_profile(username: str, user: dict = Depends(current_user)):
    """A public profile: identity, reading stats, and recent activity. When viewing your
    own profile (or as an admin) private novels are included; otherwise activity is limited
    to the shared library (global/public) so a reader's private list isn't leaked."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        target = await conn.fetchrow("SELECT * FROM users WHERE username = $1;", (username or "").lower())
        if target is None:
            raise HTTPException(status_code=404, detail="User not found.")
        tid = target["id"]
        include_private = (user["id"] == tid) or user.get("role") == "admin"

        stats = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE le.id IS NOT NULL) AS library_count,
              COUNT(*) FILTER (WHERE le.shelf = 'reading') AS reading_count,
              COUNT(*) FILTER (WHERE le.shelf = 'completed') AS completed_count,
              COALESCE(SUM(p.max_chapter_read), 0) AS chapters_read
            FROM library_entries le
            JOIN novels n ON n.id = le.novel_id
            LEFT JOIN reading_progress p ON p.novel_id = n.id AND p.user_id = le.user_id
            WHERE le.user_id = $1 AND ($2 OR n.visibility IN ('global', 'public'));
            """,
            tid, include_private,
        )

        reading = await conn.fetch(
            """
            SELECT n.id, n.title, n.cover_url, n.visibility, p.last_chapter, p.max_chapter_read, p.updated_at,
                   (SELECT MAX(number) FROM chapters c WHERE c.novel_id = n.id) AS max_chapter
            FROM reading_progress p
            JOIN novels n ON n.id = p.novel_id
            WHERE p.user_id = $1 AND p.last_chapter IS NOT NULL
              AND ($2 OR n.visibility IN ('global', 'public'))
            ORDER BY p.updated_at DESC NULLS LAST LIMIT 8;
            """,
            tid, include_private,
        )
        finished = await conn.fetch(
            """
            SELECT n.id, n.title, n.cover_url, n.visibility
            FROM library_entries le JOIN novels n ON n.id = le.novel_id
            WHERE le.user_id = $1 AND le.shelf = 'completed'
              AND ($2 OR n.visibility IN ('global', 'public'))
            ORDER BY le.added_at DESC LIMIT 8;
            """,
            tid, include_private,
        )
        published = await conn.fetch(
            """
            SELECT n.id, n.title, n.cover_url, n.visibility,
                   (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id) AS chapter_count
            FROM novels n
            WHERE n.owner_id = $1 AND n.visibility IN ('public', 'global')
            ORDER BY n.updated_at DESC NULLS LAST LIMIT 12;
            """,
            tid,
        )

    def _novel_brief(r):
        out = {"id": int(r["id"]), "title": r["title"], "cover_url": _rewrite_asset_url(r["cover_url"], int(r["id"])), "visibility": r["visibility"]}
        if "last_chapter" in r and r["last_chapter"] is not None:
            out["last_chapter"] = float(r["last_chapter"])
            out["max_chapter"] = float(r["max_chapter"]) if r["max_chapter"] is not None else None
        if "chapter_count" in r and r["chapter_count"] is not None:
            out["chapter_count"] = int(r["chapter_count"])
        return out

    profile = public_user(dict(target))
    profile["is_self"] = user["id"] == tid
    profile["role"] = target.get("role", "user") if include_private else None
    profile["stats"] = {
        "library_count": int(stats["library_count"] or 0),
        "reading_count": int(stats["reading_count"] or 0),
        "completed_count": int(stats["completed_count"] or 0),
        "chapters_read": int(stats["chapters_read"] or 0),
    }
    profile["currently_reading"] = [_novel_brief(r) for r in reading]
    profile["recently_finished"] = [_novel_brief(r) for r in finished]
    profile["published"] = [_novel_brief(r) for r in published]
    return profile


@router.post("/novels/{novel_id}/sources")
async def api_add_source(novel_id: int, payload: SourceCreate, user: dict = Depends(current_user)):
    await require_editable(novel_id, user)
    start_url = await _validated_scraper_start_url(payload.start_url)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw, chapter_offset, label)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id;
            """,
            novel_id, payload.adapter, start_url, json.dumps(payload.config or {}),
            payload.language, payload.is_raw, payload.chapter_offset, payload.label,
        )
    return {"id": int(source_id)}


@router.patch("/novels/{novel_id}/sources/{source_id}")
async def api_update_source(novel_id: int, source_id: int, payload: SourceUpdate, user: dict = Depends(current_user)):
    """Edits an existing source. Changing `chapter_offset` also renumbers that source's
    already-scraped chapters onto the new global numbering (e.g. set -1 when a raw source
    is one chapter ahead of the translation), so the fix is immediate — no re-scrape."""
    await require_editable(novel_id, user)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return {"status": "noop"}
    if "start_url" in fields and fields["start_url"] is not None:
        fields["start_url"] = await _validated_scraper_start_url(fields["start_url"])
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        owner = await conn.fetchval(
            "SELECT id FROM sources WHERE id = $1 AND novel_id = $2;", source_id, novel_id,
        )
        if not owner:
            raise HTTPException(status_code=404, detail="Source not found.")
        renumbered = 0
        try:
            async with conn.transaction():
                if "chapter_offset" in fields:
                    renumbered = await set_source_offset(conn, source_id, fields.pop("chapter_offset"))
                if fields:
                    sets, args = [], []
                    for k, v in fields.items():
                        args.append(v)
                        sets.append(f"{k} = ${len(args)}")
                    args.append(source_id)
                    await conn.execute(
                        f"UPDATE sources SET {', '.join(sets)} WHERE id = ${len(args)};", *args,
                    )
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            # e.g. the renumber would collide with another source's chapter numbers
            raise HTTPException(status_code=409, detail=f"Could not update source: {e}")
    return {"status": "success", "renumbered": renumbered}


# ── Chapters / Reader ─────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/chapters")
async def api_list_chapters(novel_id: int, user: dict = Depends(current_user)):
    """The table of contents for the reader."""
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT number, title, language, is_translated, translation_status,
                   (content IS NOT NULL OR raw_html IS NOT NULL) AS has_content,
                   word_count, kind, part_label
            FROM chapters WHERE novel_id = $1 ORDER BY number ASC;
            """,
            novel_id,
        )
    return [
        {
            "number": float(r["number"]),
            "title": r["title"],
            "language": r["language"],
            "is_translated": r["is_translated"],
            "translation_status": r["translation_status"],
            "has_content": r["has_content"],
            "word_count": r["word_count"],
            # File-import grouping: `kind` flags non-chapter sections (frontmatter/interlude/
            # backmatter); `part_label` groups chapters under a "Volume 1" heading in the TOC.
            "kind": r["kind"] or "chapter",
            "part_label": r["part_label"],
        }
        for r in rows
    ]


@router.get("/novels/{novel_id}/chapter/{number}")
async def api_get_chapter(novel_id: int, number: float, bg_tasks: BackgroundTasks, user: dict = Depends(current_user)):
    """Returns one chapter's readable content for the reader, plus prev/next numbers.
    Raw chapters are translated on demand here (and the next few are prefetched in the
    background), so the reader always gets English text — keyed off `translation_status`."""
    novel = await require_readable(novel_id, user)
    active_user = user if isinstance(user, dict) else None
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.number, c.title, c.content, c.raw_html, c.content_version, c.word_count,
                   (c.original_text IS NOT NULL) AS has_original,
                   c.language, c.is_translated, c.translation_status,
                   s.adapter, COALESCE(s.is_raw, FALSE) AS source_is_raw
            FROM chapters c LEFT JOIN sources s ON s.id = c.source_id
            WHERE c.novel_id = $1 AND c.number = $2;
            """,
            novel_id, number,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Chapter not found.")
        prev_row = await conn.fetchrow(
            "SELECT number, title FROM chapters WHERE novel_id = $1 AND number < $2 ORDER BY number DESC LIMIT 1;",
            novel_id, number,
        )
        # Adjacent titles + whether the next chapter is still raw feed the reader's
        # end-of-chapter card ("Next: Chapter 513 — Title" / "Translate & continue").
        next_row = await conn.fetchrow(
            "SELECT number, title, (content IS NULL AND original_text IS NOT NULL) AS is_raw "
            "FROM chapters WHERE novel_id = $1 AND number > $2 ORDER BY number ASC LIMIT 1;",
            novel_id, number,
        )
        prev_num = prev_row["number"] if prev_row else None
        next_num = next_row["number"] if next_row else None
        overlay = None
        if active_user is not None:
            overlay = await conn.fetchrow(
                "SELECT content, base_version, origin, conflict FROM chapter_overlays "
                "WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
                active_user["id"], novel_id, number,
            )
            await conn.execute(
                """
                INSERT INTO reading_progress (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct, updated_at)
                VALUES ($1, $2, $3, $3, 0, now())
                ON CONFLICT (user_id, novel_id) DO UPDATE SET
                    last_chapter = COALESCE(reading_progress.last_chapter, EXCLUDED.last_chapter),
                    max_chapter_read = GREATEST(
                        COALESCE(reading_progress.max_chapter_read, EXCLUDED.max_chapter_read),
                        EXCLUDED.max_chapter_read
                    ),
                    scroll_pct = COALESCE(reading_progress.scroll_pct, EXCLUDED.scroll_pct),
                    updated_at = now();
                """,
                active_user["id"], novel_id, number,
            )

    content = row["content"]
    status = row["translation_status"]
    is_translated = row["is_translated"]
    # On-demand translation for a raw chapter that hasn't been translated yet. Metered
    # against the reader's monthly quota; if they're over (or unverified), we serve the
    # chapter untranslated with a `quota_exceeded` status instead of failing the read.
    if content is None and row["has_original"]:
        result = await translate_chapter(novel_id, number, meter_user=active_user)
        content = result.get("content")
        status = result.get("status")
        is_translated = status == "done"
        # Warm the next few chapters only after the current translation actually succeeded.
        if status == "done":
            bg_tasks.add_task(prefetch_translations, novel_id, number, settings.TRANSLATE_PREFETCH, active_user)

    # Only file-import sources (epub/pdf) store sanitized rich HTML in raw_html; scraped
    # sources put the raw page dump there, which must never be rendered. And for a *raw*
    # import source the rich HTML is the source language, while `content` is the translation
    # — surfacing it would override the translation, so we only send rich HTML for non-raw
    # import sources whose content matches it.
    rich_html = row["raw_html"] if (row["adapter"] in ("epub", "pdf") and not row["source_is_raw"]) else None
    rich_html = _rewrite_rich_asset_urls(rich_html, novel_id)

    # Per-user translation overlay (Phase 5): if this reader has saved/contributed an override
    # for this chapter, the reader shows *their* text; the base is sent alongside so the
    # conflict resolver can diff base-vs-mine. `conflict` is true once the shared base has
    # advanced past the version the overlay was forked from.
    base_content = content
    base_version = int(row["content_version"] or 1)
    overlay_active = overlay is not None
    overlay_conflict = bool(overlay and (overlay["conflict"] or overlay["base_version"] < base_version))
    if overlay_active:
        content = overlay["content"]
        rich_html = None   # an overlay is plain text and replaces any rich rendering

    return {
        "number": float(row["number"]),
        "title": row["title"],
        "content": content,
        "rich_html": rich_html,
        "language": row["language"],
        "is_translated": is_translated,
        "translation_status": status,
        "word_count": int(row["word_count"]) if row["word_count"] is not None else None,
        "prev": float(prev_num) if prev_num is not None else None,
        "next": float(next_num) if next_num is not None else None,
        "prev_title": prev_row["title"] if prev_row else None,
        "next_title": next_row["title"] if next_row else None,
        "next_is_raw": bool(next_row["is_raw"]) if next_row else False,
        # Overlay / contribute-back context for the reader's editor + conflict UI.
        "content_version": base_version,
        "has_original": bool(row["has_original"]),
        "can_edit_base": can_edit(novel, active_user),
        "is_owner": active_user is not None and novel.get("owner_id") == active_user["id"],
        "contribution_policy": novel.get("contribution_policy") or "manual",
        "overlay": overlay_active,
        "overlay_origin": overlay["origin"] if overlay_active else None,
        "overlay_base_version": int(overlay["base_version"]) if overlay_active else None,
        "overlay_conflict": overlay_conflict,
        "base_content": base_content if overlay_active else None,
        # Per-chapter provenance labels for the reader (source technique + how this text was produced).
        # Keys match the frontend PROVENANCE_LABELS map so the shared badge component renders them.
        "provenance": {
            "adapter": row["adapter"],
            "imported": row["adapter"] in ("epub", "pdf"),
            "scraped": row["adapter"] is not None and row["adapter"] not in ("epub", "pdf"),
            "translated": bool(is_translated),
            "user_edited": base_version > 1 or overlay_active,
        },
    }


# ── Translation overlays + contribute-back (Phase 5) ───────────────────────
# A reader can override a shared novel's translation for their own account (an "overlay")
# and offer it back to the owner (a "contribution"). When the shared base later changes,
# overlays forked from the old version are flagged so the reader can resolve the conflict.

async def _chapter_or_404(conn, novel_id: int, number: float) -> dict:
    row = await conn.fetchrow(
        "SELECT content, content_version FROM chapters WHERE novel_id = $1 AND number = $2;",
        novel_id, number,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Chapter not found.")
    return dict(row)


async def _write_base_content(conn, novel_id: int, number: float, content: str,
                              keep_overlay_user: int | None = None) -> int:
    """Write the shared base content, bump content_version, and flag every per-user overlay
    that was forked from an older version as conflicted. The contributor whose text became the
    new base (keep_overlay_user) is exempted and re-synced to the new version instead."""
    new_version = await conn.fetchval(
        """
        UPDATE chapters
        SET content = $3, is_translated = TRUE, translation_status = 'done',
            content_version = content_version + 1
        WHERE novel_id = $1 AND number = $2 RETURNING content_version;
        """,
        novel_id, number, content,
    )
    await conn.execute(
        "UPDATE chapter_overlays SET conflict = TRUE, updated_at = now() "
        "WHERE novel_id = $1 AND chapter = $2 AND base_version < $3 AND ($4::bigint IS NULL OR user_id <> $4);",
        novel_id, number, new_version, keep_overlay_user,
    )
    if keep_overlay_user is not None:
        await conn.execute(
            "UPDATE chapter_overlays SET base_version = $3, conflict = FALSE, updated_at = now() "
            "WHERE novel_id = $1 AND chapter = $2 AND user_id = $4;",
            novel_id, number, new_version, keep_overlay_user,
        )
    return int(new_version)


@router.put("/novels/{novel_id}/chapter/{number}/content")
async def api_edit_base_content(novel_id: int, number: float, payload: OverlayUpdate, user: dict = Depends(current_user)):
    """Owner/admin: edit the shared base translation directly. Bumps the content version, so
    other readers' overlays of this chapter become conflicts they can resolve."""
    await require_editable(novel_id, user)
    text = (payload.content or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Content can't be empty.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await _chapter_or_404(conn, novel_id, number)
        async with conn.transaction():
            version = await _write_base_content(conn, novel_id, number, text)
    return {"status": "success", "content_version": version}


@router.put("/novels/{novel_id}/chapter/{number}/overlay")
async def api_save_overlay(novel_id: int, number: float, payload: OverlayUpdate, user: dict = Depends(current_user)):
    """Save the reader's personal translation override for this chapter, forked from the
    current base version. Replaces any existing overlay and clears its conflict flag."""
    await require_readable(novel_id, user)
    text = (payload.content or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Content can't be empty.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ch = await _chapter_or_404(conn, novel_id, number)
        await conn.execute(
            """
            INSERT INTO chapter_overlays (user_id, novel_id, chapter, content, base_version, origin, conflict)
            VALUES ($1, $2, $3, $4, $5, 'manual_edit', FALSE)
            ON CONFLICT (user_id, novel_id, chapter) DO UPDATE SET
                content = EXCLUDED.content, base_version = EXCLUDED.base_version,
                origin = 'manual_edit', conflict = FALSE, updated_at = now();
            """,
            user["id"], novel_id, number, text, int(ch["content_version"] or 1),
        )
    return {"status": "success"}


@router.delete("/novels/{novel_id}/chapter/{number}/overlay")
async def api_delete_overlay(novel_id: int, number: float, user: dict = Depends(current_user)):
    """Drop the reader's overlay for this chapter and fall back to the shared base."""
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM chapter_overlays WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
            user["id"], novel_id, number,
        )
    return {"status": "success"}


@router.post("/novels/{novel_id}/chapter/{number}/self-translate")
async def api_self_translate(novel_id: int, number: float, user: dict = Depends(current_user)):
    """Translate a raw chapter into the reader's own overlay (counts against their monthly
    translated-chapters quota). Only applies to chapters that have source-language text."""
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ch = await _chapter_or_404(conn, novel_id, number)
        has_source = await conn.fetchval(
            "SELECT original_text IS NOT NULL FROM chapters WHERE novel_id = $1 AND number = $2;",
            novel_id, number,
        )
    if not has_source:
        raise HTTPException(status_code=409, detail="This chapter has no source text to translate.")
    await quota.check_and_reserve(user, "translated_chapters", 1)
    translation = await translate_raw_text(novel_id, number)
    if not translation:
        raise HTTPException(status_code=409, detail="This chapter could not be translated.")
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO chapter_overlays (user_id, novel_id, chapter, content, base_version, origin, conflict)
            VALUES ($1, $2, $3, $4, $5, 'self_translated', FALSE)
            ON CONFLICT (user_id, novel_id, chapter) DO UPDATE SET
                content = EXCLUDED.content, base_version = EXCLUDED.base_version,
                origin = 'self_translated', conflict = FALSE, updated_at = now();
            """,
            user["id"], novel_id, number, translation, int(ch["content_version"] or 1),
        )
    return {"status": "success", "content": translation}


@router.post("/novels/{novel_id}/chapter/{number}/resolve")
async def api_resolve_overlay(novel_id: int, number: float, payload: ResolveOverlay, user: dict = Depends(current_user)):
    """Resolve a base-vs-overlay conflict: keep the base (drop the overlay), keep mine
    (re-anchor the overlay to the current base), or save a merged result."""
    await require_readable(novel_id, user)
    choice = (payload.choice or "").lower()
    if choice not in ("base", "mine", "merge"):
        raise HTTPException(status_code=422, detail="choice must be 'base', 'mine', or 'merge'.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        ch = await _chapter_or_404(conn, novel_id, number)
        version = int(ch["content_version"] or 1)
        if choice == "base":
            await conn.execute(
                "DELETE FROM chapter_overlays WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
                user["id"], novel_id, number,
            )
        elif choice == "mine":
            await conn.execute(
                "UPDATE chapter_overlays SET base_version = $4, conflict = FALSE, updated_at = now() "
                "WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
                user["id"], novel_id, number, version,
            )
        else:  # merge
            text = (payload.content or "").strip()
            if not text:
                raise HTTPException(status_code=422, detail="A merge needs the resolved content.")
            await conn.execute(
                """
                INSERT INTO chapter_overlays (user_id, novel_id, chapter, content, base_version, origin, conflict)
                VALUES ($1, $2, $3, $4, $5, 'manual_edit', FALSE)
                ON CONFLICT (user_id, novel_id, chapter) DO UPDATE SET
                    content = EXCLUDED.content, base_version = EXCLUDED.base_version,
                    conflict = FALSE, updated_at = now();
                """,
                user["id"], novel_id, number, text, version,
            )
    return {"status": "success"}


@router.post("/novels/{novel_id}/chapter/{number}/contribute")
async def api_contribute(novel_id: int, number: float, user: dict = Depends(current_user)):
    """Offer the reader's overlay back to the novel owner. With contribution_policy='auto'
    and no conflict (the base hasn't moved since the overlay forked) it merges into the base
    immediately; otherwise it lands in the owner's review inbox as a pending contribution."""
    novel = await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        overlay = await conn.fetchrow(
            "SELECT content, base_version FROM chapter_overlays WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
            user["id"], novel_id, number,
        )
        if overlay is None:
            raise HTTPException(status_code=409, detail="You have no edit to offer for this chapter.")
        ch = await _chapter_or_404(conn, novel_id, number)
        version = int(ch["content_version"] or 1)
        is_clean = overlay["base_version"] >= version
        auto = (novel.get("contribution_policy") == "auto") and is_clean

        async with conn.transaction():
            status = "auto_merged" if auto else "pending"
            cid = await conn.fetchval(
                """
                INSERT INTO contributions (novel_id, from_user_id, chapter, content, base_version, status, reviewed_at)
                VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $7 THEN now() ELSE NULL END)
                RETURNING id;
                """,
                novel_id, user["id"], number, overlay["content"], int(overlay["base_version"]), status, auto,
            )
            if auto:
                await _write_base_content(conn, novel_id, number, overlay["content"], keep_overlay_user=user["id"])
    return {"status": "auto_merged" if auto else "pending", "id": int(cid)}


@router.get("/novels/{novel_id}/contributions")
async def api_list_contributions(novel_id: int, status: str = "pending", user: dict = Depends(current_user)):
    """Owner/admin inbox of contribute-back offers (defaults to pending)."""
    await require_editable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT k.id, k.chapter, k.content, k.base_version, k.status, k.created_at,
                   u.username AS from_username, u.display_name AS from_display_name,
                   c.content AS base_content, c.content_version
            FROM contributions k
            JOIN users u ON u.id = k.from_user_id
            LEFT JOIN chapters c ON c.novel_id = k.novel_id AND c.number = k.chapter
            WHERE k.novel_id = $1 AND ($2 = 'all' OR k.status = $2)
            ORDER BY k.created_at DESC LIMIT 200;
            """,
            novel_id, status,
        )
    return [
        {
            "id": int(r["id"]), "chapter": float(r["chapter"]), "content": r["content"],
            "base_version": int(r["base_version"]), "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "from_username": r["from_username"], "from_display_name": r["from_display_name"] or r["from_username"],
            "base_content": r["base_content"],
            "is_conflict": r["content_version"] is not None and int(r["base_version"]) < int(r["content_version"]),
        }
        for r in rows
    ]


@router.post("/novels/{novel_id}/contributions/{contribution_id}/accept")
async def api_accept_contribution(
    novel_id: int,
    contribution_id: int,
    payload: ContributionAccept | None = None,
    user: dict = Depends(current_user),
):
    """Owner/admin: merge a pending contribution into the shared base. If the shared base
    changed after the contribution was offered, callers must provide resolved content so a
    stale proposal cannot overwrite newer translation work by accident."""
    await require_editable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow(
            "SELECT id, chapter, content, from_user_id, base_version, status FROM contributions WHERE id = $1 AND novel_id = $2;",
            contribution_id, novel_id,
        )
        if c is None:
            raise HTTPException(status_code=404, detail="Contribution not found.")
        if c["status"] not in ("pending",):
            raise HTTPException(status_code=409, detail=f"Contribution is already '{c['status']}'.")
        ch = await _chapter_or_404(conn, novel_id, float(c["chapter"]))
        is_conflict = int(c["base_version"] or 1) < int(ch["content_version"] or 1)
        resolved = ((payload.content if payload else None) or "").strip()
        if is_conflict and not resolved:
            raise HTTPException(
                status_code=409,
                detail="This contribution conflicts with the current base. Provide resolved content to accept it.",
            )
        content = resolved or c["content"]
        async with conn.transaction():
            await _write_base_content(conn, novel_id, float(c["chapter"]), content, keep_overlay_user=c["from_user_id"])
            await conn.execute(
                "UPDATE contributions SET status = 'accepted', content = $3, reviewed_by = $2, reviewed_at = now() WHERE id = $1;",
                contribution_id, user["id"], content,
            )
    return {"status": "accepted"}


@router.post("/novels/{novel_id}/contributions/{contribution_id}/reject")
async def api_reject_contribution(novel_id: int, contribution_id: int, user: dict = Depends(current_user)):
    """Owner/admin: decline a pending contribution (the contributor keeps their overlay)."""
    await require_editable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            "UPDATE contributions SET status = 'rejected', reviewed_by = $3, reviewed_at = now() "
            "WHERE id = $1 AND novel_id = $2 AND status = 'pending' RETURNING id;",
            contribution_id, novel_id, user["id"],
        )
    if updated is None:
        raise HTTPException(status_code=404, detail="No pending contribution with that id.")
    return {"status": "rejected"}


# ── Tag suggestions ────────────────────────────────────────────────────────
# Status tags are owner/admin-controlled. A reader of a shared (public/global) novel can
# propose a tag set; the owner/admin accepts (applies it) or rejects it.

async def api_suggest_tags(novel_id: int, payload: TagSuggestion, user: dict = Depends(current_user)):
    """A reader proposes a status-tag set for a shared novel they can see but can't edit."""
    from novelwiki.bootstrap.catalog import build_catalog_migration_service
    from novelwiki.modules.catalog.adapters.inbound.http import api_suggest_tags as handler

    return await handler(
        novel_id, payload, user=user, service=await build_catalog_migration_service()
    )


async def api_list_tag_suggestions(novel_id: int, status: str = "pending", user: dict = Depends(current_user)):
    """Owner/admin inbox of tag-suggestion proposals (defaults to pending)."""
    from novelwiki.bootstrap.catalog import build_catalog_migration_service
    from novelwiki.modules.catalog.adapters.inbound.http import api_list_tag_suggestions as handler

    return await handler(
        novel_id, status, user=user, service=await build_catalog_migration_service()
    )


async def api_accept_tag_suggestion(novel_id: int, suggestion_id: int, user: dict = Depends(current_user)):
    """Owner/admin: apply a suggested tag set to the novel and mark the suggestion accepted."""
    from novelwiki.bootstrap.catalog import build_catalog_migration_service
    from novelwiki.modules.catalog.adapters.inbound.http import api_accept_tag_suggestion as handler

    return await handler(
        novel_id, suggestion_id, user=user,
        service=await build_catalog_migration_service(),
    )


async def api_reject_tag_suggestion(novel_id: int, suggestion_id: int, user: dict = Depends(current_user)):
    """Owner/admin: decline a tag suggestion."""
    from novelwiki.bootstrap.catalog import build_catalog_migration_service
    from novelwiki.modules.catalog.adapters.inbound.http import api_reject_tag_suggestion as handler

    return await handler(
        novel_id, suggestion_id, user=user,
        service=await build_catalog_migration_service(),
    )


# Compatibility callables for tests/scripts that imported the old private route module.
# HTTP registration belongs to the Reading inbound adapter above; these have no decorators.
async def _reading_service_compat(conn):
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.reading.adapters.outbound.postgres import PostgresReadingRepository
    from novelwiki.modules.reading.application.services import ReadingService

    return ReadingService(
        PostgresReadingRepository(conn),
        CatalogAccessService(PostgresCatalogRepository(conn)),
    )


async def api_get_progress(novel_id: int, user: dict):
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        progress = await (await _reading_service_compat(conn)).get_progress(
            novel_id, Principal.from_user(user)
        )
    return {
        "last_chapter": progress.last_chapter,
        "max_chapter_read": progress.max_chapter_read,
        "scroll_pct": progress.scroll_pct,
    }


async def api_set_progress(novel_id: int, payload: ProgressUpdate, user: dict):
    from novelwiki.kernel.errors import NotFound
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            await (await _reading_service_compat(conn)).set_progress(
                novel_id, Principal.from_user(user), payload.last_chapter, payload.scroll_pct
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success"}


async def api_list_bookmarks(novel_id: int, user: dict):
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await (await _reading_service_compat(conn)).list_bookmarks(
            novel_id, Principal.from_user(user)
        )
    return [
        {"id": row.id, "chapter": row.chapter, "note": row.note,
         "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows
    ]


async def api_add_bookmark(novel_id: int, payload: BookmarkCreate, user: dict):
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        bookmark_id = await (await _reading_service_compat(conn)).add_bookmark(
            novel_id, Principal.from_user(user), payload.chapter, payload.note
        )
    return {"id": bookmark_id}


async def api_delete_bookmark(novel_id: int, bookmark_id: int, user: dict):
    from novelwiki.modules.identity.public import Principal

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await (await _reading_service_compat(conn)).delete_bookmark(
            novel_id, Principal.from_user(user), bookmark_id
        )
    return {"status": "success"}


# ── Scraping ──────────────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/scrape")
async def api_scrape(novel_id: int, payload: ScrapeTrigger, user: dict = Depends(current_user)):
    """Schedules a durable scrape job (survives restarts). Targets one source if source_id is
    given, else every source of the novel. Repeated clicks for the same target dedupe onto the
    already-active job rather than piling up duplicate work."""
    await require_editable(novel_id, user)
    quota.require_spend_allowed(user)
    pool = await get_db_pool()
    if payload.source_id is not None:
        async with pool.acquire() as conn:
            source = await conn.fetchrow(
                "SELECT id FROM sources WHERE id = $1 AND novel_id = $2;",
                payload.source_id, novel_id,
            )
        if not source:
            raise HTTPException(status_code=404, detail="Source not found.")
        idem = (
            f"scrape:novel{novel_id}:source{payload.source_id}:"
            f"force{int(payload.force)}:max{payload.max_chapters}"
        )
    else:
        idem = f"scrape:novel{novel_id}:all:force{int(payload.force)}:max{payload.max_chapters}"
    job_id, created = await jobs_service.create_job(
        "scrape", novel_id=novel_id, user_id=user["id"],
        options={"source_id": payload.source_id, "force": payload.force, "max_chapters": payload.max_chapters},
        idempotency_key=idem,
    )
    msg = "Scrape job scheduled." if created else "A scrape for this target is already running."
    return {"status": "success", "message": msg, "job_id": job_id, "deduped": not created}


# ── Translation + glossary ────────────────────────────────────────────────

async def api_translate(novel_id: int, payload: TranslateTrigger, user: dict = Depends(current_user)):
    """Schedule a durable translation batch over a chapter range (manual batch; reading itself
    uses on-demand + prefetch). The worker computes the pending chapters at execution time,
    meters each against the caller's monthly quota as it translates, and stops gracefully on
    quota exhaustion. Optionally seeds the glossary from the codex first."""
    from novelwiki.bootstrap.translation import build_translation_scheduling_service
    from novelwiki.modules.identity.adapters.principals import principal_from_user
    from novelwiki.modules.translation.adapters.inbound.http import api_translate as handler

    return await handler(
        novel_id, payload, user=user,
        service=await build_translation_scheduling_service(),
        principal_factory=principal_from_user,
    )


async def api_seed_glossary(novel_id: int, user: dict = Depends(current_user)):
    """Seed the glossary's English spellings from the established codex entities."""
    from novelwiki.bootstrap.translation import build_glossary_service
    from novelwiki.modules.translation.adapters.inbound.http import api_seed_glossary as handler

    return await handler(novel_id, user=user, service=await build_glossary_service())


async def api_list_glossary(novel_id: int, user: dict = Depends(current_user)):
    from novelwiki.bootstrap.translation import build_glossary_service
    from novelwiki.modules.translation.adapters.inbound.http import api_list_glossary as handler

    return await handler(novel_id, user=user, service=await build_glossary_service())


async def api_upsert_glossary(novel_id: int, payload: GlossaryUpsert, user: dict = Depends(current_user)):
    """Add or update a glossary term (manual edits win and are typically locked)."""
    from novelwiki.bootstrap.translation import build_glossary_service
    from novelwiki.modules.translation.adapters.inbound.http import api_upsert_glossary as handler

    return await handler(
        novel_id, payload, user=user, service=await build_glossary_service()
    )


async def api_delete_glossary(novel_id: int, term_id: int, user: dict = Depends(current_user)):
    from novelwiki.bootstrap.translation import build_glossary_service
    from novelwiki.modules.translation.adapters.inbound.http import api_delete_glossary as handler

    return await handler(
        novel_id, term_id, user=user, service=await build_glossary_service()
    )


# ── Codex: meta / stats ───────────────────────────────────────────────────

@router.get("/novels/{novel_id}/meta")
async def api_meta_chapters(novel_id: int, user: dict = Depends(current_user)):
    """Chapter span + display title/blurb so the codex ceiling control can be bounded."""
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=None)
    novel = ceiling_info.novel
    return {
        "novel_title": novel["title"],
        "novel_blurb": novel["description"] or "",
        "count": ceiling_info.chapter_count,
        "min_chapter": ceiling_info.min_chapter,
        "max_chapter": ceiling_info.max_chapter,
        "allowed_ceiling": ceiling_info.allowed_ceiling,
        "effective_ceiling": ceiling_info.effective_ceiling,
    }


@router.get("/novels/{novel_id}/stats")
async def api_meta_stats(novel_id: int, ceiling: float, user: dict = Depends(current_user)):
    """Spoiler-safe aggregate stats for the codex home surface (all bounded by ceiling)."""
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=ceiling)
    ceiling = ceiling_info.effective_ceiling
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        entities_revealed = await conn.fetchval(
            "SELECT COUNT(*) FROM entities WHERE first_seen_chapter <= $1 AND novel_id = $2;", ceiling, novel_id
        )
        facts_known = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM entity_facts f
            JOIN entities e ON e.id = f.entity_id AND e.novel_id = f.novel_id
            WHERE f.chapter <= $1 AND f.novel_id = $2 AND e.first_seen_chapter <= $1;
            """,
            ceiling, novel_id,
        )
        relationships_known = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM relationships r
            JOIN entities e1 ON e1.id = r.source_id AND e1.novel_id = r.novel_id
            JOIN entities e2 ON e2.id = r.target_id AND e2.novel_id = r.novel_id
            WHERE r.chapter <= $1 AND r.novel_id = $2
              AND e1.first_seen_chapter <= $1 AND e2.first_seen_chapter <= $1;
            """,
            ceiling, novel_id,
        )
        max_chapter = await conn.fetchval("SELECT MAX(number) FROM chapters WHERE novel_id = $1;", novel_id)
        title_row = await conn.fetchrow(
            "SELECT number, title FROM chapters WHERE number <= $1 AND novel_id = $2 ORDER BY number DESC LIMIT 1;",
            ceiling, novel_id,
        )
    max_f = float(max_chapter) if max_chapter is not None else None
    pct = 0
    if max_f and max_f > 0:
        pct = round(min(100.0, (float(ceiling) / max_f) * 100))
    return {
        "ceiling": float(ceiling),
        "requested_ceiling": ceiling_info.requested_ceiling,
        "allowed_ceiling": ceiling_info.allowed_ceiling,
        "effective_ceiling": ceiling_info.effective_ceiling,
        "ceiling_clamped": ceiling_info.clamped,
        "entities_revealed": int(entities_revealed or 0),
        "facts_known": int(facts_known or 0),
        "relationships_known": int(relationships_known or 0),
        "pct_read": pct,
        "max_chapter": max_f,
        "ceiling_chapter": float(title_row["number"]) if title_row else None,
        "ceiling_title": title_row["title"] if title_row else None,
    }


# ── Codex: structured wiki ────────────────────────────────────────────────

@router.get("/novels/{novel_id}/entities")
async def api_list_entities(
    novel_id: int,
    ceiling: float,
    type: str | None = None,
    q: str | None = None,
    user: dict = Depends(current_user),
):
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=ceiling)
    try:
        return await list_entities(
            novel_id,
            chapter_ceiling=ceiling_info.effective_ceiling,
            entity_type=type,
            name_query=q,
        )
    except Exception as e:
        logger.error(f"Error listing entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/resolve")
async def api_resolve_entity(novel_id: int, name: str, ceiling: float, user: dict = Depends(current_user)):
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=ceiling)
    try:
        return await resolve_entity(novel_id, name=name, chapter_ceiling=ceiling_info.effective_ceiling)
    except Exception as e:
        logger.error(f"Error resolving entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}")
async def api_get_entity_profile(
    novel_id: int,
    entity_id: int,
    ceiling: float,
    user: dict = Depends(current_user),
):
    """Structured profile at the ceiling, using the wiki_cache fast path."""
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=ceiling)
    ceiling = ceiling_info.effective_ceiling
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            cached_row = await conn.fetchrow(
                "SELECT rendered_md FROM wiki_cache WHERE novel_id = $1 AND entity_id = $2 AND chapter_ceiling = $3;",
                novel_id, entity_id, ceiling,
            )

        profile = await get_entity_profile(novel_id, entity_id=entity_id, chapter_ceiling=ceiling)
        if not profile:
            raise HTTPException(status_code=404, detail="Entity not found or not yet visible.")

        if cached_row:
            profile["rendered_md"] = cached_row["rendered_md"]
            return profile

        # Cache miss → synthesizing this profile calls a Pro model, so it goes through the
        # same read-side AI cost controls as /ask: a verified-email spend gate plus per-user
        # hourly-rate and concurrency limits. A cache hit above never reaches this.
        if settings.ENTITY_PROFILE_SYNTH_REQUIRE_VERIFIED:
            quota.require_spend_allowed(user)
        async with ai_limits.concurrency_slot(user, "profile"):
            await ai_limits.consume_ask_rate(user, "profile")

            canonical_name = profile["canonical_name"]
            aliases = ", ".join(profile["aliases"]) if profile["aliases"] else "None"
            facts_str = "\n".join([
                f"- [Fact {f['id']}, Ch {f['chapter']}] ({f['fact_type']}): {f['content']}"
                for f in profile["facts"]
            ]) if profile["facts"] else "No facts recorded."

            rels = await get_relationships(novel_id, entity_id, ceiling)
            rels_str = "\n".join([
                f"- [Rel {r['id']}, Ch {r['chapter']}] {r['source_name']} ({r['relation_type']}) {r['target_name']}: {r['content'] or ''}"
                for r in rels
            ]) if rels else "No relationships recorded."

            messages = [
                {"role": "system", "content": WIKI_PROFILE_SYNTHESIS_SYSTEM.format(chapter_ceiling=ceiling)},
                {
                    "role": "user",
                    "content": WIKI_PROFILE_SYNTHESIS_USER.format(
                        canonical_name=canonical_name, type=profile["type"], chapter_ceiling=ceiling,
                        aliases=aliases, facts=facts_str, relationships=rels_str,
                    )
                }
            ]
            rendered_md = await call_chat_completion(model=settings.MODEL_PRO, messages=messages, temperature=0.0)

            evidence_ids = {"fact_ids": [f["id"] for f in profile["facts"]], "rel_ids": [r["id"] for r in rels]}
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO wiki_cache (novel_id, entity_id, chapter_ceiling, rendered_md, model, evidence_ids)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (novel_id, entity_id, chapter_ceiling) DO UPDATE
                    SET rendered_md = EXCLUDED.rendered_md, model = EXCLUDED.model, evidence_ids = EXCLUDED.evidence_ids;
                    """,
                    novel_id, entity_id, ceiling, rendered_md, settings.MODEL_PRO, json.dumps(evidence_ids),
                )

        profile["rendered_md"] = rendered_md
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}/relationships")
async def api_get_relationships(
    novel_id: int,
    entity_id: int,
    ceiling: float,
    other_id: int | None = None,
    user: dict = Depends(current_user),
):
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=ceiling)
    try:
        return await get_relationships(
            novel_id,
            entity_id=entity_id,
            chapter_ceiling=ceiling_info.effective_ceiling,
            other_id=other_id,
        )
    except Exception as e:
        logger.error(f"Error fetching relationships: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}/timeline")
async def api_get_timeline(novel_id: int, entity_id: int, ceiling: float, user: dict = Depends(current_user)):
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=ceiling)
    try:
        return await get_timeline(
            novel_id,
            entity_id=entity_id,
            chapter_ceiling=ceiling_info.effective_ceiling,
        )
    except Exception as e:
        logger.error(f"Error fetching timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}/identities")
async def api_get_identities(novel_id: int, entity_id: int, ceiling: float, user: dict = Depends(current_user)):
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=ceiling)
    try:
        return await get_identity_links(
            novel_id,
            entity_id=entity_id,
            chapter_ceiling=ceiling_info.effective_ceiling,
        )
    except Exception as e:
        logger.error(f"Error fetching identity links: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Codex: Q&A + build ────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/ask", response_model=AskResponse)
async def ask_question(novel_id: int, req: AskRequest, user: dict = Depends(current_user)):
    """Agentic spoiler-safe Q&A scoped to one novel.

    A cached answer (same normalized question + effective ceiling) is served cheaply and
    bypasses every cost gate. An uncached question fans out to embeddings, rerank, and
    several model calls, so it must clear the read-side AI cost controls first: a length
    cap (checked before any provider call), a verified-email spend gate, a per-user hourly
    cap on uncached asks, and a small concurrency ceiling."""
    # 1. Length cap — reject before touching the ceiling/DB/providers.
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question can't be empty.")
    if len(question) > settings.ASK_MAX_QUERY_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Question is too long (max {settings.ASK_MAX_QUERY_CHARS} characters).",
        )

    # 2. Effective (server-trusted) ceiling — never above what this reader has actually read.
    ceiling_info = await require_effective_ceiling(novel_id, user, requested_ceiling=req.ceiling)
    ceiling = ceiling_info.effective_ceiling

    def _resp(result: dict) -> AskResponse:
        return AskResponse(
            answer=result["answer"],
            citations=[Citation(**c) for c in result["citations"]],
            evidence_ids=result["evidence_ids"],
            requested_ceiling=ceiling_info.requested_ceiling,
            allowed_ceiling=ceiling_info.allowed_ceiling,
            effective_ceiling=ceiling_info.effective_ceiling,
            ceiling_clamped=ceiling_info.clamped,
        )

    # 3. Cache fast path — free, no spend/rate/concurrency charge.
    query_hash = compute_query_hash(question)
    cached = await get_cached_answer(novel_id, query_hash, ceiling)
    if cached:
        citations = await build_citations(novel_id, cached["answer_md"], ceiling)
        return _resp({"answer": cached["answer_md"], "citations": citations, "evidence_ids": cached["evidence_ids"]})

    # 4. Cache miss → real provider work. Gate it.
    if settings.ASK_REQUIRE_VERIFIED:
        quota.require_spend_allowed(user)   # 403 unless verified/admin
    try:
        async with ai_limits.concurrency_slot(user, "ask"):        # 429 if too many in flight
            await ai_limits.consume_ask_rate(user, "ask")          # 429 if over the hourly cap
            await get_bm25_manager(novel_id).ensure_loaded()
            result = await answer_question(novel_id, question, ceiling)
        return _resp(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agentic Q&A error: {e}")
        raise HTTPException(status_code=502, detail="The AI service failed to answer. Please try again.")


@router.post("/novels/{novel_id}/codex/build")
async def api_codex_build(novel_id: int, payload: CodexBuild, user: dict = Depends(current_user)):
    """Schedule a durable codex build (chunk → embed → extract → rebuild BM25) that survives
    restarts. Repeated clicks for the same range dedupe onto the active job so the expensive
    build runs once, and the reserved codex-build quota is refunded if the job ultimately fails
    or is cancelled (the durable worker finalizes it)."""
    await require_editable(novel_id, user)
    if (payload.from_chapter is not None and payload.to_chapter is not None
            and payload.from_chapter > payload.to_chapter):
        raise HTTPException(status_code=422, detail="from_chapter must be less than or equal to to_chapter.")
    idem = f"codex:novel{novel_id}:{payload.from_chapter}:{payload.to_chapter}:{int(payload.force)}"

    # A build already running for this exact target? Return it without charging again.
    existing = await jobs_service.find_active("codex_build", idem)
    if existing is not None:
        view = jobs_service.job_view(existing)
        return {"status": "success", "message": "A codex build for this range is already running.",
                "job_id": int(existing["id"]), "deduped": True,
                "execution_backend": view["execution_backend"], "model": view["backend_model"],
                "backend_reason": "already_active"}

    decision = await resolve_backend(user, Workload.CODEX_EXTRACT, payload.ai_backend)

    # Reserve the codex-build credit up front (429 if over quota), recording the reservation on the
    # job so the worker can refund it on failure/cancel.
    await quota.check_and_reserve(user, "codex_builds", 1)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE novels SET codex_enabled = TRUE WHERE id = $1;", novel_id)
    try:
        job_id, created = await jobs_service.create_job(
            "codex_build", novel_id=novel_id, user_id=user["id"],
            options={"force": payload.force, "from_chapter": payload.from_chapter, "to_chapter": payload.to_chapter},
            idempotency_key=idem, quota_kind="codex_builds", quota_reserved=1,
            max_attempts=settings.AGY_MAX_ATTEMPTS if decision.resolved.value == "agy" else None,
            **decision.as_job_fields(),
        )
    except (jobs_service.ActiveJobLimitError, jobs_service.BackendPolicyChangedError) as exc:
        await quota.refund(user["id"], "codex_builds", 1)
        status = 429 if isinstance(exc, jobs_service.ActiveJobLimitError) else 409
        raise HTTPException(status_code=status, detail=str(exc))
    if not created:
        # Lost a race to a concurrent identical request — give the credit we just reserved back.
        await quota.refund(user["id"], "codex_builds", 1)
    msg = "Codex build scheduled." if created else "A codex build for this range is already running."
    return {"status": "success", "message": msg, "job_id": job_id, "deduped": not created,
            "execution_backend": decision.resolved.value, "model": decision.model,
            "backend_reason": decision.reason}


# Compatibility callables for legacy imports; HTTP registration belongs to Work.
from novelwiki.modules.work.adapters.inbound.http import (
    api_cancel_job,
    api_get_job,
    api_list_jobs,
)


@router.post("/novels/{novel_id}/merge-entities")
async def trigger_merge(novel_id: int, payload: MergePayload, user: dict = Depends(current_user)):
    await require_editable(novel_id, user)
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await merge_entities(novel_id, payload.keep_id, payload.drop_id, conn)
        return {"status": "success", "message": f"Entity {payload.drop_id} merged into {payload.keep_id}."}
    except Exception as e:
        logger.error(f"Error merging entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── File import (EPUB/PDF ingestion) ──────────────────────────────────────
# Upload → parse/segment (worker) → review/edit the plan → commit into chapters. The
# heavy work runs in the durable import worker (not BackgroundTasks) so it survives a
# restart; these endpoints just mutate import_jobs and return its state.

class PlanUpdate(BaseModel):
    plan: dict                       # the full edited plan (frontend sends it back wholesale)

class ImportCommit(BaseModel):
    mode: str = "new"                # new | append | replace
    novel_id: int | None = None      # required when mode == append
    source_id: int | None = None     # required when mode == replace
    offset: float = 0                # append/replace: global = segment number + offset
    is_raw: bool | None = None        # override the raw/translate flag (None = keep detected)

class OcrConfirm(BaseModel):
    gemini_first: bool = False       # skip the sidecar, OCR every page with Gemini directly

class ImportInit(BaseModel):
    filename: str                    # used only for its extension (.epub/.pdf)
    size: int = 0                    # declared total bytes (for the completion check)

class ImportBatch(BaseModel):
    path: str | None = None          # folder to scan; defaults to IMPORT_INCOMING_DIR
    recursive: bool = True           # walk subfolders (Calibre stores book-per-folder)
    auto_commit: bool = False        # commit each book without a manual review step
    group_series: bool = False       # group EPUB volumes of one series into a single novel

class CommitSeries(BaseModel):
    job_ids: list[int]               # parsed jobs to fold into one multi-volume novel


_IMPORT_FORMATS = {".epub": "epub", ".pdf": "pdf"}


async def _read_limited_request_body(request: Request, max_bytes: int) -> bytes:
    """Read an octet-stream request incrementally, rejecting as soon as it crosses max_bytes."""
    data = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="Chunk too large.")
    return bytes(data)


def _job_view(job: dict) -> dict:
    """Trim a job row to what the UI needs (drops the on-disk original path)."""
    return {
        "id": int(job["id"]),
        "novel_id": int(job["novel_id"]) if job.get("novel_id") is not None else None,
        "format": job["format"],
        "status": job["status"],
        "stage": job.get("stage"),
        "filename": os.path.basename(job.get("original_path") or "") or None,
        "detected_meta": job.get("detected_meta") or {},
        "plan": job.get("plan"),
        "stats": job.get("stats") or {},
        "cost_estimate": job.get("cost_estimate"),
        "progress": job.get("progress") or {},
        "options": job.get("options") or {},
        "error": job.get("error"),
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "updated_at": job["updated_at"].isoformat() if job.get("updated_at") else None,
    }


# Import jobs are owned by their uploader. Owner-or-admin may view/act on a job; everyone
# else gets a 404 (so a job's existence isn't leaked).
def _job_owned(job: dict, user: dict) -> bool:
    if user.get("role") == "admin":
        return True
    return job.get("user_id") is not None and job["user_id"] == user["id"]


async def _require_own_job(job_id: int, user: dict) -> dict:
    from novelwiki.importer import jobs as import_jobs
    job = await import_jobs.get_job(job_id)
    if not job or not _job_owned(job, user):
        raise HTTPException(status_code=404, detail="Import job not found.")
    return job


def _asset_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; object-src 'none'; script-src 'none'; sandbox",
    }


def _safe_asset_filename(filename: str) -> tuple[str, str, str]:
    from novelwiki.importer import storage as import_storage
    if os.path.basename(filename) != filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404, detail="Asset not found.")
    match = _ASSET_FILENAME_RE.fullmatch(filename or "")
    if not match:
        raise HTTPException(status_code=404, detail="Asset not found.")
    sha = match.group("sha").lower()
    ext = match.group("ext").lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in import_storage.ALLOWED_ASSET_EXTS:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return sha, ext, f"{sha}.{ext}"


def _safe_child_path(root: Path, child: Path) -> Path:
    root = root.resolve()
    child = child.resolve()
    if child != root and root not in child.parents:
        raise HTTPException(status_code=404, detail="Asset not found.")
    return child


def _asset_file_response(path: Path, mime: str | None) -> FileResponse:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found.")
    from novelwiki.importer import storage as import_storage
    return FileResponse(
        path,
        media_type=mime or import_storage.mime_from_ext(path.suffix),
        headers=_asset_headers(),
    )


@router.get("/assets/novels/{novel_id}/{filename}")
async def api_novel_asset(novel_id: int, filename: str, user: dict = Depends(current_user)):
    """Serve a committed imported image only if the caller can read the novel."""
    from novelwiki.importer import storage as import_storage
    await require_readable(novel_id, user)
    sha, _ext, safe_name = _safe_asset_filename(filename)
    rel = import_storage.asset_rel(novel_id, sha, safe_name.rsplit(".", 1)[1])
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        asset = await conn.fetchrow(
            "SELECT path, mime FROM assets WHERE novel_id = $1 AND sha256 = $2 AND path = $3;",
            novel_id, sha, rel,
        )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found.")
    root = import_storage.asset_file_path(novel_id, "__root__").parent
    path = _safe_child_path(root, import_storage.asset_file_path(novel_id, safe_name))
    return _asset_file_response(path, asset["mime"])


@router.get("/assets/import-jobs/{job_id}/{filename}")
async def api_import_job_asset(job_id: int, filename: str, user: dict = Depends(current_user)):
    """Serve a staged import preview image only to the job owner or an admin."""
    from novelwiki.importer import storage as import_storage
    job = await _require_own_job(job_id, user)
    sha, _ext, safe_name = _safe_asset_filename(filename)
    meta = job.get("detected_meta") or {}
    cover_sha = (meta.get("cover_sha") or "").lower()
    if cover_sha and cover_sha != sha:
        raise HTTPException(status_code=404, detail="Asset not found.")
    root = import_storage.staged_asset_file_path(job_id, "__root__").parent
    path = _safe_child_path(root, import_storage.staged_asset_file_path(job_id, safe_name))
    return _asset_file_response(path, import_storage.mime_from_ext(safe_name.rsplit(".", 1)[1]))


@router.post("/import/upload")
async def api_import_upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """Accept an uploaded EPUB, stash it under a fresh job id, and queue it for parsing."""
    from novelwiki.importer import jobs as import_jobs
    from novelwiki.importer import storage as import_storage

    quota.require_spend_allowed(user)

    ext = os.path.splitext(file.filename or "")[1].lower()
    fmt = _IMPORT_FORMATS.get(ext)
    if not fmt:
        raise HTTPException(status_code=400, detail="Only .epub and .pdf files are supported.")

    # Insert as 'receiving' so the worker can't grab it before the blob lands on disk.
    job_id = await import_jobs.create_job(fmt, original_path="", status="receiving", user_id=user["id"])
    try:
        path, sha, size = await import_storage.save_upload_file_limited(
            job_id,
            file,
            ext,
            settings.MAX_UPLOAD_MB * 1024 * 1024,
        )
        if size <= 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    except ValueError:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM import_jobs WHERE id = $1;", job_id)
        import_storage.cleanup_job(job_id)
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload cap.")
    except HTTPException:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM import_jobs WHERE id = $1;", job_id)
        import_storage.cleanup_job(job_id)
        raise
    await import_jobs.update_job(
        job_id, original_path=str(path), file_sha256=sha, status="uploaded",
    )
    # Re-import detection: if these exact bytes were imported before, tell the UI so it can
    # warn ("you already imported this") instead of silently making a duplicate novel.
    duplicate_of = await import_jobs.imports_with_hash(sha, exclude_job_id=job_id)
    return {"id": job_id, "status": "uploaded", "format": fmt, "duplicate_of": duplicate_of}


def _iter_import_files(root: str, recursive: bool):
    """Yield (path, filename) for every importable EPUB/PDF under `root`. Recursive mode
    walks subfolders, which is how a Calibre library (book-per-folder) is laid out."""
    if recursive:
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() in _IMPORT_FORMATS:
                    yield os.path.join(dirpath, name), name
    else:
        try:
            names = sorted(os.listdir(root))
        except FileNotFoundError:
            return
        for name in names:
            src = os.path.join(root, name)
            if os.path.isfile(src) and os.path.splitext(name)[1].lower() in _IMPORT_FORMATS:
                yield src, name


async def _enqueue_batch(files, *, auto_commit: bool, group_series: bool, user_id: int | None = None):
    """Stage a list of (path, filename) into fresh import jobs sharing one batch id, so the
    worker can group/auto-commit them. Returns the queued job descriptors."""
    import uuid
    from novelwiki.importer import jobs as import_jobs
    from novelwiki.importer import storage as import_storage

    import_storage.ensure_dirs()
    batch_id = uuid.uuid4().hex
    options = {"batch_id": batch_id, "auto_commit": auto_commit, "group_series": group_series}
    queued = []
    for src, name in files:
        ext = os.path.splitext(name)[1].lower()
        fmt = _IMPORT_FORMATS[ext]
        job_id = await import_jobs.create_job(fmt, original_path="", options=options, status="receiving", user_id=user_id)
        path, sha, _size = import_storage.save_original_from_path(job_id, src, ext)
        await import_jobs.update_job(
            job_id, original_path=str(path),
            file_sha256=sha, status="uploaded",
        )
        queued.append({"id": job_id, "filename": name})
    return batch_id, queued


@router.post("/import/scan-incoming")
async def api_import_scan_incoming(user: dict = Depends(require_admin)):
    """Enqueue any EPUB/PDF dropped into IMPORT_INCOMING_DIR (the watched-folder path for big
    files that bypass the multipart upload cap). Non-recursive, manual review per book."""
    files = list(_iter_import_files(settings.IMPORT_INCOMING_DIR, recursive=False))
    _batch_id, queued = await _enqueue_batch(files, auto_commit=False, group_series=False, user_id=user["id"])
    return {"queued": queued, "count": len(queued)}


@router.post("/import/batch")
async def api_import_batch(payload: ImportBatch, user: dict = Depends(require_admin)):
    """Bulk-import a folder (e.g. a Calibre library). Recurses by default, can auto-commit
    each book without review, and can group EPUB volumes of one series into a single novel."""
    root = payload.path or settings.IMPORT_INCOMING_DIR
    if not os.path.isdir(root):
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")
    files = list(_iter_import_files(root, recursive=payload.recursive))
    if not files:
        raise HTTPException(status_code=404, detail=f"No .epub/.pdf files found under {root}.")
    batch_id, queued = await _enqueue_batch(
        files, auto_commit=payload.auto_commit, group_series=payload.group_series, user_id=user["id"])
    return {"batch_id": batch_id, "queued": queued, "count": len(queued)}


# ── Resumable chunked upload (big files over the tunnel) ────────────────────
# init → (chunk … chunk) → complete. The on-disk blob size is the resume cursor, so a
# dropped connection just resumes from GET .../status. The job stays 'receiving' (not a
# worker trigger) until complete flips it to 'uploaded'.

@router.post("/import/upload/init")
async def api_import_upload_init(payload: ImportInit, user: dict = Depends(current_user)):
    from novelwiki.importer import jobs as import_jobs
    from novelwiki.importer import storage as import_storage

    quota.require_spend_allowed(user)

    ext = os.path.splitext(payload.filename or "")[1].lower()
    fmt = _IMPORT_FORMATS.get(ext)
    if not fmt:
        raise HTTPException(status_code=400, detail="Only .epub and .pdf files are supported.")
    # A declared total is mandatory: it bounds disk use up front (before any bytes land) and
    # is what the completion check compares against.
    size = int(payload.size or 0)
    if size <= 0:
        raise HTTPException(status_code=422, detail="A positive declared file size is required.")
    max_bytes = settings.MAX_CHUNKED_UPLOAD_MB * 1024 * 1024
    if size > max_bytes:
        raise HTTPException(status_code=413,
                            detail=f"File exceeds the {settings.MAX_CHUNKED_UPLOAD_MB} MB upload cap.")
    job_id = await import_jobs.create_job(
        fmt, original_path="", options={"upload": {"size": size, "ext": ext.lstrip('.')}},
        status="receiving", user_id=user["id"])
    path = import_storage.init_upload(job_id, ext)
    await import_jobs.update_job(job_id, original_path=str(path))
    return {"id": job_id, "offset": 0, "format": fmt}


@router.get("/import/upload/{job_id}/status")
async def api_import_upload_status(job_id: int, user: dict = Depends(current_user)):
    from novelwiki.importer import jobs as import_jobs
    from novelwiki.importer import storage as import_storage
    job = await _require_own_job(job_id, user)
    up = (job.get("options") or {}).get("upload") or {}
    ext = up.get("ext", job["format"])
    return {"id": job_id, "offset": import_storage.upload_offset(job_id, ext),
            "size": up.get("size", 0), "complete": job["status"] != "receiving"}


@router.put("/import/upload/{job_id}/chunk")
async def api_import_upload_chunk(job_id: int, request: Request, user: dict = Depends(current_user)):
    """Append one chunk at the byte offset given in the `Upload-Offset` header.

    The chunk must start exactly at the current resume cursor (contiguous, append-only), fit
    the per-chunk cap, and not push the running total past the declared size — so a client
    can't punch gaps, forge a sparse file, or blow past the size committed to at init. A stale
    offset gets a 409 carrying the real cursor so the client can resync; a chunk that re-sends
    already-received bytes is an idempotent no-op only when those bytes actually match what's
    stored. Every accepted chunk bumps the session's `updated_at` so an upload still in progress
    isn't read as abandoned by the cleanup sweep."""
    from novelwiki.importer import storage as import_storage
    from novelwiki.importer import jobs as import_jobs
    job = await _require_own_job(job_id, user)
    if job["status"] != "receiving":
        raise HTTPException(status_code=409, detail="Upload session is not open.")
    up = (job.get("options") or {}).get("upload") or {}
    ext = up.get("ext", job["format"])
    declared = int(up.get("size") or 0)
    try:
        offset = int(request.headers.get("Upload-Offset", "0"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Upload-Offset header.")
    if offset < 0:
        raise HTTPException(status_code=400, detail="Upload-Offset must be non-negative.")
    data = await _read_limited_request_body(request, settings.UPLOAD_CHUNK_MAX_MB * 1024 * 1024)
    if not data:
        raise HTTPException(status_code=400, detail="Empty chunk.")

    current = import_storage.upload_offset(job_id, ext)
    # Idempotent retry: these bytes already landed in full. Accept as a no-op ONLY if they match
    # what's stored — a resend of different bytes for a received range is a conflict, not a no-op.
    if offset + len(data) <= current:
        if not import_storage.chunk_matches(job_id, ext, offset, data):
            raise HTTPException(status_code=409, detail="Chunk conflicts with already-received bytes.",
                                headers={"Upload-Offset": str(current)})
        await import_jobs.touch_job(job_id)
        return {"offset": current}
    # Anything else that doesn't start exactly at the cursor would gap or partially overlap.
    if offset != current:
        raise HTTPException(status_code=409, detail="Stale upload offset; resume from the current cursor.",
                            headers={"Upload-Offset": str(current)})
    if declared and offset + len(data) > declared:
        raise HTTPException(status_code=413, detail="Chunk would exceed the declared upload size.")

    new_offset = import_storage.write_chunk(job_id, ext, offset, data)
    await import_jobs.touch_job(job_id)
    return {"offset": new_offset}


@router.post("/import/upload/{job_id}/complete")
async def api_import_upload_complete(job_id: int, user: dict = Depends(current_user)):
    from novelwiki.importer import jobs as import_jobs
    from novelwiki.importer import storage as import_storage
    quota.require_spend_allowed(user)
    job = await _require_own_job(job_id, user)
    if job["status"] != "receiving":
        return {"id": job_id, "status": job["status"]}    # already finalized (idempotent)
    up = (job.get("options") or {}).get("upload") or {}
    ext = up.get("ext", job["format"])
    declared = int(up.get("size") or 0)
    if declared <= 0:
        raise HTTPException(status_code=400, detail="Upload has no declared size; re-initialize the upload.")
    # Cheap stat-based completeness check before the (streaming) hash, so an incomplete or
    # over-long blob is rejected without reading the whole file. The job stays 'receiving'
    # (the client can send the rest and retry complete); it only flips to 'uploaded' once the
    # bytes are all present and hashed.
    size = import_storage.upload_offset(job_id, ext)
    if size != declared:
        raise HTTPException(status_code=400,
                            detail=f"Upload incomplete: have {size} bytes, expected {declared}.")
    sha, _size = import_storage.finalize_upload(job_id, ext)
    await import_jobs.update_job(job_id, file_sha256=sha, status="uploaded", stage=None)
    duplicate_of = await import_jobs.imports_with_hash(sha, exclude_job_id=job_id)
    return {"id": job_id, "status": "uploaded", "format": job["format"], "duplicate_of": duplicate_of}


@router.post("/import/commit-series")
async def api_import_commit_series(payload: CommitSeries, user: dict = Depends(current_user)):
    """Fold several parsed jobs into one multi-volume novel (ordered by series index)."""
    from novelwiki.importer import commit as import_commit
    if len(payload.job_ids) < 1:
        raise HTTPException(status_code=422, detail="Provide at least one job id.")
    for jid in payload.job_ids:
        job = await _require_own_job(jid, user)
        if job["status"] not in ("awaiting_review", "failed"):
            raise HTTPException(status_code=409, detail=f"Job {jid} is '{job['status']}', not ready to commit.")
    try:
        result = await import_commit.commit_series(payload.job_ids)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return result


@router.get("/import/jobs")
async def api_import_jobs(user: dict = Depends(current_user)):
    from novelwiki.importer import jobs as import_jobs
    # Admins see every job; everyone else only their own uploads.
    scope = None if user.get("role") == "admin" else user["id"]
    return [_job_view(j) for j in await import_jobs.list_jobs(user_id=scope)]


@router.get("/import/jobs/{job_id}")
async def api_import_job(job_id: int, user: dict = Depends(current_user)):
    job = await _require_own_job(job_id, user)
    return _job_view(job)


@router.put("/import/jobs/{job_id}/plan")
async def api_import_update_plan(job_id: int, payload: PlanUpdate, user: dict = Depends(current_user)):
    """Replace the editable segmentation plan (merge/split/rename/include/number/kind are
    all client-side edits that produce a new plan). Block ranges are validated against the
    stored block stream so a bad edit can't point off the end of the document."""
    from novelwiki.importer import jobs as import_jobs
    from novelwiki.importer import storage as import_storage

    job = await _require_own_job(job_id, user)
    if job["status"] in ("committing", "committed"):
        raise HTTPException(status_code=409, detail="This job has already been committed.")

    segments = payload.plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise HTTPException(status_code=422, detail="Plan must contain a non-empty 'segments' list.")
    try:
        n_blocks = len(import_storage.load_blocks(job_id).blocks)
    except Exception:
        n_blocks = None
    for s in segments:
        rng = s.get("block_range")
        if not (isinstance(rng, list) and len(rng) == 2 and isinstance(rng[0], int) and isinstance(rng[1], int)
                and 0 <= rng[0] <= rng[1] and (n_blocks is None or rng[1] < n_blocks)):
            raise HTTPException(status_code=422, detail=f"Segment '{s.get('id')}' has an invalid block_range.")

    payload.plan.setdefault("version", 1)
    await import_jobs.update_job(job_id, plan=payload.plan)
    return {"status": "success"}


@router.post("/import/jobs/{job_id}/commit")
async def api_import_commit(job_id: int, payload: ImportCommit, user: dict = Depends(current_user)):
    """Hand the job to the worker for commit: stamp the target into options and flip the
    status to 'committing'. The worker writes chapters via the scraper persist path."""
    from novelwiki.importer import jobs as import_jobs
    job = await _require_own_job(job_id, user)
    # When appending/replacing, the user must also be able to edit the target novel.
    if payload.mode == "append" and payload.novel_id:
        await require_editable(payload.novel_id, user)
    elif payload.mode == "replace" and payload.source_id:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            tgt_novel = await conn.fetchval("SELECT novel_id FROM sources WHERE id = $1;", payload.source_id)
        if tgt_novel:
            await require_editable(int(tgt_novel), user)
    # 'committed' is intentionally excluded: a finished job already produced its novel, and
    # re-committing 'new' would duplicate it. Re-import the file for a fresh copy instead.
    if job["status"] not in ("awaiting_review", "failed"):
        raise HTTPException(status_code=409, detail=f"Job is '{job['status']}', not ready to commit.")
    if not (job.get("plan") and job["plan"].get("segments")):
        raise HTTPException(status_code=409, detail="Job has no plan to commit; re-parse it first.")

    if payload.mode == "append":
        if not payload.novel_id:
            raise HTTPException(status_code=422, detail="Append mode requires a novel_id.")
        target = {"novel_id": payload.novel_id, "offset": payload.offset}
    elif payload.mode == "replace":
        if not payload.source_id:
            raise HTTPException(status_code=422, detail="Replace mode requires a source_id.")
        target = {"source_id": payload.source_id, "offset": payload.offset}
    else:
        target = "new"

    options = {**(job.get("options") or {}), "target": target}
    # Raw source → the importer stores the source-language text and the reader translates it
    # on demand. Honour an explicit choice from the review UI; otherwise keep whatever the
    # parser auto-detected (non-English book / CJK scan).
    if payload.is_raw is not None:
        options["is_raw"] = payload.is_raw
    await import_jobs.update_job(job_id, options=options, status="committing", error=None)
    return {"status": "committing"}


@router.post("/import/jobs/{job_id}/confirm-ocr")
async def api_import_confirm_ocr(job_id: int, payload: OcrConfirm, user: dict = Depends(current_user)):
    """Approve the (expensive) OCR run for a scanned PDF: the job leaves the confirm gate and
    the worker starts reading pages (sidecar + Gemini escalation, budget-guarded)."""
    from novelwiki.importer import jobs as import_jobs
    quota.require_spend_allowed(user)
    job = await _require_own_job(job_id, user)
    if job["status"] not in ("awaiting_ocr_confirm", "ocr_paused"):
        raise HTTPException(status_code=409, detail=f"Job is '{job['status']}', not awaiting OCR confirmation.")
    # Reserve the estimated OCR pages against the user's monthly quota up front (this is the
    # user-facing approval gate, so a 429 here is the right place to surface "over quota").
    pages = int(((job.get("cost_estimate") or {}).get("pages")) or ((job.get("progress") or {}).get("total")) or 0)
    if pages > 0:
        await quota.check_and_reserve(user, "ocr_pages", pages)
    options = {**(job.get("options") or {}), "gemini_first": payload.gemini_first}
    await import_jobs.update_job(job_id, options=options, status="ocr_pending",
                                 stage="OCR queued", error=None)
    return {"status": "ocr_pending"}


@router.post("/import/jobs/{job_id}/cancel")
async def api_import_cancel(job_id: int, user: dict = Depends(current_user)):
    from novelwiki.importer import jobs as import_jobs
    await _require_own_job(job_id, user)
    await import_jobs.update_job(job_id, status="canceled", stage="canceled")
    return {"status": "canceled"}


@router.delete("/import/jobs/{job_id}")
async def api_import_delete(job_id: int, user: dict = Depends(current_user)):
    """Delete a job row and free its scratch dir + staged assets."""
    from novelwiki.importer import storage as import_storage
    await _require_own_job(job_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM import_jobs WHERE id = $1;", job_id)
    import_storage.cleanup_job(job_id)
    return {"status": "success"}
