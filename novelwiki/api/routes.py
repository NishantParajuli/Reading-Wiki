import logging
import json
import os
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Request, Depends
from pydantic import BaseModel
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.deps import current_user, require_admin
from novelwiki.auth.access import require_readable, require_editable
from novelwiki import quota
from novelwiki.scraper.runner import scrape_source, scrape_novel, set_source_offset
from novelwiki.scraper.adapters import list_adapters
from novelwiki.ingest.chunk import chunk_all_chapters
from novelwiki.ingest.embed import embed_missing_chunks
from novelwiki.ingest.extract import extract_all_chapters
from novelwiki.ingest.link import merge_entities
from novelwiki.translate.translate import (
    translate_chapter, prefetch_translations, translate_range, seed_glossary_from_entities,
)
from novelwiki.retrieval.bm25 import get_bm25_manager
from novelwiki.retrieval.tools import (
    resolve_entity, get_entity_profile, get_relationships, get_timeline,
    list_entities, get_identity_links
)
from novelwiki.agent.orchestrator import answer_question
from novelwiki.agent.llm_client import call_chat_completion
from novelwiki.agent.prompts import WIKI_PROFILE_SYNTHESIS_SYSTEM, WIKI_PROFILE_SYNTHESIS_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Shelves a novel can sit on (user reading status) and the user-applied status tags.
SHELVES = {"to_read", "reading", "completed"}
STATUS_TAGS = {"ongoing", "finished", "translation_ongoing"}


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

class VisibilityUpdate(BaseModel):
    visibility: str          # private|public|global

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


# ── Adapters ──────────────────────────────────────────────────────────────

@router.get("/adapters")
async def api_adapters():
    """The scraping techniques available for the Add-Source dropdown."""
    return list_adapters()


# ── Library / Novels ──────────────────────────────────────────────────────

@router.get("/novels")
async def api_list_novels(user: dict = Depends(current_user)):
    """The caller's library grid: the Global shared library + novels they own or added,
    each with their own shelf/tags and reading progress."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id, n.title, n.author, n.cover_url, n.description, n.codex_enabled,
                   n.visibility, n.owner_id,
                   COALESCE(le.shelf, n.shelf) AS shelf,
                   COALESCE(le.status_tags, n.status_tags) AS status_tags,
                   COUNT(c.number) AS chapter_count,
                   MIN(c.number) AS min_chapter, MAX(c.number) AS max_chapter,
                   p.last_chapter, p.max_chapter_read,
                   (SELECT bool_or(s.is_raw)     FROM sources s WHERE s.novel_id = n.id) AS has_raw,
                   (SELECT bool_or(NOT s.is_raw)  FROM sources s WHERE s.novel_id = n.id) AS has_eng
            FROM novels n
            LEFT JOIN library_entries le ON le.novel_id = n.id AND le.user_id = $1
            LEFT JOIN reading_progress p ON p.novel_id = n.id AND p.user_id = $1
            LEFT JOIN chapters c ON c.novel_id = n.id
            WHERE n.visibility = 'global' OR n.owner_id = $1 OR le.id IS NOT NULL
            GROUP BY n.id, le.shelf, le.status_tags, p.last_chapter, p.max_chapter_read
            ORDER BY n.updated_at DESC NULLS LAST, n.id DESC;
            """,
            user["id"],
        )
    return [
        {
            "id": int(r["id"]),
            "title": r["title"],
            "author": r["author"],
            "cover_url": r["cover_url"],
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
        }
        for r in rows
    ]


@router.post("/novels")
async def api_create_novel(payload: NovelCreate, user: dict = Depends(current_user)):
    """Create a novel (owned by the caller, private by default) and optionally its first source."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            novel_id = await conn.fetchval(
                """
                INSERT INTO novels (title, author, description, cover_url, original_language, codex_enabled,
                                    owner_id, visibility)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'private') RETURNING id;
                """,
                payload.title, payload.author, payload.description, payload.cover_url,
                payload.original_language, payload.codex_enabled, user["id"],
            )
            # The owner's novel shows up in their library immediately.
            await conn.execute(
                "INSERT INTO library_entries (user_id, novel_id) VALUES ($1, $2) "
                "ON CONFLICT (user_id, novel_id) DO NOTHING;",
                user["id"], novel_id,
            )
            source_id = None
            if payload.source:
                s = payload.source
                source_id = await conn.fetchval(
                    """
                    INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw, chapter_offset, label)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id;
                    """,
                    novel_id, s.adapter, s.start_url, json.dumps(s.config or {}),
                    s.language, s.is_raw, s.chapter_offset, s.label,
                )
    return {"id": int(novel_id), "source_id": int(source_id) if source_id else None}


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
            "SELECT shelf, status_tags FROM library_entries WHERE novel_id = $1 AND user_id = $2;",
            novel_id, user["id"],
        )
    has_raw = any(s["is_raw"] for s in sources) if sources else None
    has_eng = any(not s["is_raw"] for s in sources) if sources else None
    return {
        "id": int(novel["id"]),
        "title": novel["title"],
        "author": novel["author"],
        "description": novel["description"],
        "cover_url": novel["cover_url"],
        "original_language": novel["original_language"],
        "codex_enabled": novel["codex_enabled"],
        "visibility": novel["visibility"],
        "is_owner": novel["owner_id"] == user["id"],
        "can_edit": novel["owner_id"] == user["id"] or user.get("role") == "admin",
        "contribution_policy": novel["contribution_policy"],
        "shelf": (entry["shelf"] if entry else None) or novel["shelf"],
        "status_tags": list((entry["status_tags"] if entry else None) or novel["status_tags"] or []),
        "translation_type": _translation_type(has_raw, has_eng),
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


@router.patch("/novels/{novel_id}")
async def api_update_novel(novel_id: int, payload: NovelUpdate, user: dict = Depends(current_user)):
    """Edit a novel. Shelf/tags are *per-user* (stored in library_entries) and any reader may
    set them. Metadata (title, author, description, cover, codex toggle) is owner/admin only."""
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return {"status": "noop"}
    novel = await require_readable(novel_id, user)

    # Per-user curation → library_entries (upsert). Blank shelf clears; tags whitelisted.
    shelf_set = "shelf" in fields
    tags_set = "status_tags" in fields
    shelf_val = None
    if shelf_set:
        shelf = (fields.pop("shelf") or "").strip().lower()
        if shelf and shelf not in SHELVES:
            raise HTTPException(status_code=422, detail=f"Unknown shelf '{shelf}'.")
        shelf_val = shelf or None
    tags_val = None
    if tags_set:
        tags = [t.strip().lower() for t in (fields.pop("status_tags") or [])]
        tags_val = [t for t in dict.fromkeys(tags) if t in STATUS_TAGS]

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        if shelf_set or tags_set:
            await conn.execute(
                """
                INSERT INTO library_entries (user_id, novel_id, shelf, status_tags)
                VALUES ($1, $2, $3, COALESCE($4::text[], '{}'::text[]))
                ON CONFLICT (user_id, novel_id) DO UPDATE SET
                    shelf = CASE WHEN $5 THEN EXCLUDED.shelf ELSE library_entries.shelf END,
                    status_tags = CASE WHEN $6 THEN EXCLUDED.status_tags ELSE library_entries.status_tags END;
                """,
                user["id"], novel_id, shelf_val, tags_val, shelf_set, tags_set,
            )

        # Remaining keys are base metadata — owner/admin only.
        if fields:
            if not (novel["owner_id"] == user["id"] or user.get("role") == "admin"):
                raise HTTPException(status_code=403, detail="You don't have permission to edit this novel.")
            sets, args = [], []
            for k, v in fields.items():
                args.append(v)
                sets.append(f"{k} = ${len(args)}")
            args.append(novel_id)
            await conn.execute(
                f"UPDATE novels SET {', '.join(sets)}, updated_at = now() WHERE id = ${len(args)};",
                *args,
            )
    return {"status": "success"}


@router.delete("/novels/{novel_id}")
async def api_delete_novel(novel_id: int, user: dict = Depends(current_user)):
    await require_editable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # Collect the novel's import scratch dirs before the cascade nulls the references,
        # so we can free those on-disk files too (they aren't FK-cascaded).
        job_ids = [int(r["id"]) for r in await conn.fetch(
            "SELECT id FROM import_jobs WHERE novel_id = $1;", novel_id
        )]
        await conn.execute("DELETE FROM novels WHERE id = $1;", novel_id)
    # The assets/import_jobs rows cascade with the novel, but the files on disk do not.
    from novelwiki.importer.storage import cleanup_novel_assets, cleanup_job
    cleanup_novel_assets(novel_id)
    for jid in job_ids:
        cleanup_job(jid)
    return {"status": "success"}


# ── Visibility, discovery & personal library ────────────────────────────────

VISIBILITIES = {"private", "public", "global"}


@router.patch("/novels/{novel_id}/visibility")
async def api_set_visibility(novel_id: int, payload: VisibilityUpdate, user: dict = Depends(current_user)):
    """Change a novel's visibility. Owner/admin only; only an admin may set/clear `global`
    (the curated shared library). Publishing to `global` reassigns ownership to the admin."""
    v = (payload.visibility or "").strip().lower()
    if v not in VISIBILITIES:
        raise HTTPException(status_code=422, detail=f"visibility must be one of {sorted(VISIBILITIES)}.")
    novel = await require_editable(novel_id, user)
    is_admin = user.get("role") == "admin"
    if (v == "global" or novel["visibility"] == "global") and not is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can manage the Global library.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        if v == "global":
            # Promote into the curated library: the admin becomes the steward/owner.
            await conn.execute(
                "UPDATE novels SET visibility = 'global', owner_id = $2, updated_at = now() WHERE id = $1;",
                novel_id, user["id"],
            )
        else:
            await conn.execute(
                "UPDATE novels SET visibility = $2, updated_at = now() WHERE id = $1;", novel_id, v,
            )
    return {"status": "success", "visibility": v}


@router.get("/discover")
async def api_discover(user: dict = Depends(current_user), q: str | None = None):
    """Browse the shared library — Global + Public novels the caller hasn't added yet."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id, n.title, n.author, n.cover_url, n.description, n.visibility,
                   u.username AS owner_username,
                   COUNT(c.number) AS chapter_count
            FROM novels n
            LEFT JOIN users u ON u.id = n.owner_id
            LEFT JOIN chapters c ON c.novel_id = n.id
            LEFT JOIN library_entries le ON le.novel_id = n.id AND le.user_id = $1
            WHERE n.visibility IN ('global', 'public')
              AND n.owner_id IS DISTINCT FROM $1
              AND le.id IS NULL
              AND ($2::text IS NULL OR n.title ILIKE '%' || $2 || '%')
            GROUP BY n.id, u.username
            ORDER BY (n.visibility = 'global') DESC, n.updated_at DESC NULLS LAST, n.id DESC
            LIMIT 200;
            """,
            user["id"], q,
        )
    return [
        {"id": int(r["id"]), "title": r["title"], "author": r["author"], "cover_url": r["cover_url"],
         "description": r["description"], "visibility": r["visibility"], "owner_username": r["owner_username"],
         "chapter_count": int(r["chapter_count"] or 0)}
        for r in rows
    ]


@router.post("/novels/{novel_id}/library")
async def api_add_to_library(novel_id: int, user: dict = Depends(current_user)):
    """Add a readable (global/public/owned) novel to the caller's personal library."""
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO library_entries (user_id, novel_id) VALUES ($1, $2) "
            "ON CONFLICT (user_id, novel_id) DO NOTHING;",
            user["id"], novel_id,
        )
    return {"status": "success"}


@router.delete("/novels/{novel_id}/library")
async def api_remove_from_library(novel_id: int, user: dict = Depends(current_user)):
    """Remove a novel from the caller's library (their progress/bookmarks are kept)."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM library_entries WHERE user_id = $1 AND novel_id = $2;", user["id"], novel_id,
        )
    return {"status": "success"}


@router.get("/me/usage")
async def api_my_usage(user: dict = Depends(current_user)):
    """The caller's monthly spend vs. their quota (drives the account panel)."""
    return await quota.usage_and_limits(user)


@router.post("/novels/{novel_id}/sources")
async def api_add_source(novel_id: int, payload: SourceCreate, user: dict = Depends(current_user)):
    await require_editable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw, chapter_offset, label)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id;
            """,
            novel_id, payload.adapter, payload.start_url, json.dumps(payload.config or {}),
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
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.number, c.title, c.content, c.raw_html,
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
        prev_num = await conn.fetchval(
            "SELECT number FROM chapters WHERE novel_id = $1 AND number < $2 ORDER BY number DESC LIMIT 1;",
            novel_id, number,
        )
        next_num = await conn.fetchval(
            "SELECT number FROM chapters WHERE novel_id = $1 AND number > $2 ORDER BY number ASC LIMIT 1;",
            novel_id, number,
        )

    content = row["content"]
    status = row["translation_status"]
    is_translated = row["is_translated"]
    # On-demand translation for a raw chapter that hasn't been translated yet. Metered
    # against the reader's monthly quota; if they're over (or unverified), we serve the
    # chapter untranslated with a `quota_exceeded` status instead of failing the read.
    if content is None and row["has_original"]:
        result = await translate_chapter(novel_id, number, meter_user=user)
        content = result.get("content")
        status = result.get("status")
        is_translated = status == "done"
        # Warm the next few chapters only after the current translation actually succeeded.
        if status == "done":
            bg_tasks.add_task(prefetch_translations, novel_id, number, settings.TRANSLATE_PREFETCH, user)

    # Only file-import sources (epub/pdf) store sanitized rich HTML in raw_html; scraped
    # sources put the raw page dump there, which must never be rendered. And for a *raw*
    # import source the rich HTML is the source language, while `content` is the translation
    # — surfacing it would override the translation, so we only send rich HTML for non-raw
    # import sources whose content matches it.
    rich_html = row["raw_html"] if (row["adapter"] in ("epub", "pdf") and not row["source_is_raw"]) else None

    return {
        "number": float(row["number"]),
        "title": row["title"],
        "content": content,
        "rich_html": rich_html,
        "language": row["language"],
        "is_translated": is_translated,
        "translation_status": status,
        "prev": float(prev_num) if prev_num is not None else None,
        "next": float(next_num) if next_num is not None else None,
    }


# ── Reading progress ──────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/progress")
async def api_get_progress(novel_id: int, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM reading_progress WHERE novel_id = $1 AND user_id = $2;", novel_id, user["id"]
        )
    if not row:
        return {"last_chapter": None, "max_chapter_read": None, "scroll_pct": 0}
    return {
        "last_chapter": float(row["last_chapter"]) if row["last_chapter"] is not None else None,
        "max_chapter_read": float(row["max_chapter_read"]) if row["max_chapter_read"] is not None else None,
        "scroll_pct": float(row["scroll_pct"] or 0),
    }


@router.put("/novels/{novel_id}/progress")
async def api_set_progress(novel_id: int, payload: ProgressUpdate, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO reading_progress (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct, updated_at)
            VALUES ($1, $2, $3, $3, $4, now())
            ON CONFLICT (user_id, novel_id) DO UPDATE SET
                last_chapter = EXCLUDED.last_chapter,
                max_chapter_read = GREATEST(COALESCE(reading_progress.max_chapter_read, 0), EXCLUDED.last_chapter),
                scroll_pct = EXCLUDED.scroll_pct,
                updated_at = now();
            """,
            user["id"], novel_id, payload.last_chapter, payload.scroll_pct,
        )
    return {"status": "success"}


# ── Bookmarks ─────────────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/bookmarks")
async def api_list_bookmarks(novel_id: int, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chapter, note, created_at FROM bookmarks "
            "WHERE novel_id = $1 AND user_id = $2 ORDER BY chapter ASC;",
            novel_id, user["id"],
        )
    return [
        {"id": int(r["id"]), "chapter": float(r["chapter"]), "note": r["note"],
         "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]


@router.post("/novels/{novel_id}/bookmarks")
async def api_add_bookmark(novel_id: int, payload: BookmarkCreate, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        bid = await conn.fetchval(
            "INSERT INTO bookmarks (user_id, novel_id, chapter, note) VALUES ($1, $2, $3, $4) RETURNING id;",
            user["id"], novel_id, payload.chapter, payload.note,
        )
    return {"id": int(bid)}


@router.delete("/novels/{novel_id}/bookmarks/{bookmark_id}")
async def api_delete_bookmark(novel_id: int, bookmark_id: int, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM bookmarks WHERE id = $1 AND novel_id = $2 AND user_id = $3;",
            bookmark_id, novel_id, user["id"],
        )
    return {"status": "success"}


# ── Scraping ──────────────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/scrape")
async def api_scrape(novel_id: int, payload: ScrapeTrigger, bg_tasks: BackgroundTasks, user: dict = Depends(current_user)):
    """Kicks off scraping in the background. Targets one source if source_id is given,
    else every source of the novel."""
    await require_editable(novel_id, user)
    if payload.source_id is not None:
        bg_tasks.add_task(scrape_source, payload.source_id, force=payload.force, max_chapters=payload.max_chapters)
    else:
        bg_tasks.add_task(scrape_novel, novel_id, force=payload.force, max_chapters=payload.max_chapters)
    return {"status": "success", "message": "Scrape job scheduled in background."}


# ── Translation + glossary ────────────────────────────────────────────────

@router.post("/novels/{novel_id}/translate")
async def api_translate(novel_id: int, payload: TranslateTrigger, bg_tasks: BackgroundTasks, user: dict = Depends(current_user)):
    """Translate raw chapters in a range in the background (manual batch; reading
    itself uses on-demand + prefetch). Optionally seed the glossary from the codex first."""
    # Spend on the shared base is owner/admin only (per-user self-translation is Phase 5).
    await require_editable(novel_id, user)
    # Meter against the caller's monthly quota: count the chapters this run will actually
    # translate (pending raws in range, or all raws in range when force=True).
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        pending = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chapters
            WHERE novel_id = $1 AND original_text IS NOT NULL
              AND ($4 OR content IS NULL)
              AND ($2::numeric IS NULL OR number >= $2)
              AND ($3::numeric IS NULL OR number <= $3);
            """,
            novel_id, payload.from_chapter, payload.to_chapter, payload.force,
        )
    await quota.check_available(user, "translated_chapters", int(pending or 0))

    async def _job():
        if payload.seed_from_codex:
            await seed_glossary_from_entities(novel_id)
        await translate_range(novel_id, payload.from_chapter, payload.to_chapter, payload.force, meter_user=user)
    bg_tasks.add_task(_job)
    return {"status": "success", "message": "Translation job scheduled in background.", "chapters": int(pending or 0)}


@router.post("/novels/{novel_id}/glossary/seed")
async def api_seed_glossary(novel_id: int, user: dict = Depends(current_user)):
    """Seed the glossary's English spellings from the established codex entities."""
    await require_editable(novel_id, user)
    n = await seed_glossary_from_entities(novel_id)
    return {"status": "success", "seeded": n}


@router.get("/novels/{novel_id}/glossary")
async def api_list_glossary(novel_id: int, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source_term, translation, term_type, notes, locked
            FROM translation_glossary WHERE novel_id = $1
            ORDER BY locked DESC, term_type NULLS LAST, source_term ASC;
            """,
            novel_id,
        )
    return [
        {"id": int(r["id"]), "source_term": r["source_term"], "translation": r["translation"],
         "term_type": r["term_type"], "notes": r["notes"], "locked": r["locked"]}
        for r in rows
    ]


@router.put("/novels/{novel_id}/glossary")
async def api_upsert_glossary(novel_id: int, payload: GlossaryUpsert, user: dict = Depends(current_user)):
    """Add or update a glossary term (manual edits win and are typically locked)."""
    await require_editable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        gid = await conn.fetchval(
            """
            INSERT INTO translation_glossary (novel_id, source_term, translation, term_type, notes, locked)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (novel_id, source_term) DO UPDATE
            SET translation = EXCLUDED.translation, term_type = EXCLUDED.term_type,
                notes = EXCLUDED.notes, locked = EXCLUDED.locked
            RETURNING id;
            """,
            novel_id, payload.source_term.strip(), payload.translation.strip(),
            payload.term_type, payload.notes, payload.locked,
        )
    return {"id": int(gid)}


@router.delete("/novels/{novel_id}/glossary/{term_id}")
async def api_delete_glossary(novel_id: int, term_id: int, user: dict = Depends(current_user)):
    await require_editable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM translation_glossary WHERE id = $1 AND novel_id = $2;", term_id, novel_id)
    return {"status": "success"}


# ── Codex: meta / stats ───────────────────────────────────────────────────

@router.get("/novels/{novel_id}/meta")
async def api_meta_chapters(novel_id: int, user: dict = Depends(current_user)):
    """Chapter span + display title/blurb so the codex ceiling control can be bounded."""
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        novel = await conn.fetchrow("SELECT title, description FROM novels WHERE id = $1;", novel_id)
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS count, MIN(number) AS min_chapter, MAX(number) AS max_chapter FROM chapters WHERE novel_id = $1;",
            novel_id,
        )
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found.")
    return {
        "novel_title": novel["title"],
        "novel_blurb": novel["description"] or "",
        "count": int(row["count"]),
        "min_chapter": float(row["min_chapter"]) if row["min_chapter"] is not None else None,
        "max_chapter": float(row["max_chapter"]) if row["max_chapter"] is not None else None,
    }


@router.get("/novels/{novel_id}/stats")
async def api_meta_stats(novel_id: int, ceiling: float, user: dict = Depends(current_user)):
    """Spoiler-safe aggregate stats for the codex home surface (all bounded by ceiling)."""
    await require_readable(novel_id, user)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        entities_revealed = await conn.fetchval(
            "SELECT COUNT(*) FROM entities WHERE first_seen_chapter <= $1 AND novel_id = $2;", ceiling, novel_id
        )
        facts_known = await conn.fetchval(
            "SELECT COUNT(*) FROM entity_facts WHERE chapter <= $1 AND novel_id = $2;", ceiling, novel_id
        )
        relationships_known = await conn.fetchval(
            "SELECT COUNT(*) FROM relationships WHERE chapter <= $1 AND novel_id = $2;", ceiling, novel_id
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
    await require_readable(novel_id, user)
    try:
        return await list_entities(novel_id, chapter_ceiling=ceiling, entity_type=type, name_query=q)
    except Exception as e:
        logger.error(f"Error listing entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/resolve")
async def api_resolve_entity(novel_id: int, name: str, ceiling: float, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    try:
        return await resolve_entity(novel_id, name=name, chapter_ceiling=ceiling)
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
    await require_readable(novel_id, user)
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
    await require_readable(novel_id, user)
    try:
        return await get_relationships(novel_id, entity_id=entity_id, chapter_ceiling=ceiling, other_id=other_id)
    except Exception as e:
        logger.error(f"Error fetching relationships: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}/timeline")
async def api_get_timeline(novel_id: int, entity_id: int, ceiling: float, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    try:
        return await get_timeline(novel_id, entity_id=entity_id, chapter_ceiling=ceiling)
    except Exception as e:
        logger.error(f"Error fetching timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}/identities")
async def api_get_identities(novel_id: int, entity_id: int, ceiling: float, user: dict = Depends(current_user)):
    await require_readable(novel_id, user)
    try:
        return await get_identity_links(novel_id, entity_id=entity_id, chapter_ceiling=ceiling)
    except Exception as e:
        logger.error(f"Error fetching identity links: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Codex: Q&A + build ────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/ask", response_model=AskResponse)
async def ask_question(novel_id: int, req: AskRequest, user: dict = Depends(current_user)):
    """Agentic spoiler-safe Q&A scoped to one novel."""
    await require_readable(novel_id, user)
    try:
        await get_bm25_manager(novel_id).ensure_loaded()
        result = await answer_question(novel_id, req.question, req.ceiling)
        return AskResponse(
            answer=result["answer"],
            citations=[Citation(**c) for c in result["citations"]],
            evidence_ids=result["evidence_ids"],
        )
    except Exception as e:
        logger.error(f"Agentic Q&A error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _build_codex(novel_id: int, force: bool, from_chapter: float | None, to_chapter: float | None):
    """Full codex pipeline for one novel: chunk -> embed -> extract -> rebuild BM25."""
    await chunk_all_chapters(novel_id, force=force, from_chapter=from_chapter, to_chapter=to_chapter)
    await embed_missing_chunks(novel_id, from_chapter=from_chapter, to_chapter=to_chapter)
    await extract_all_chapters(novel_id, force=force, from_chapter=from_chapter, to_chapter=to_chapter)
    await get_bm25_manager(novel_id).rebuild()


@router.post("/novels/{novel_id}/codex/build")
async def api_codex_build(novel_id: int, payload: CodexBuild, bg_tasks: BackgroundTasks, user: dict = Depends(current_user)):
    """Builds (or rebuilds) the spoiler-safe codex for a novel in the background."""
    await require_editable(novel_id, user)
    await quota.check_and_reserve(user, "codex_builds", 1)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE novels SET codex_enabled = TRUE WHERE id = $1;", novel_id)
    bg_tasks.add_task(_build_codex, novel_id, payload.force, payload.from_chapter, payload.to_chapter)
    return {"status": "success", "message": "Codex build scheduled in background."}


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

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {settings.MAX_UPLOAD_MB} MB upload cap.")

    # Insert as 'receiving' so the worker can't grab it before the blob lands on disk.
    job_id = await import_jobs.create_job(fmt, original_path="", status="receiving", user_id=user["id"])
    path = import_storage.save_original(job_id, data, ext)
    sha = import_storage.sha256_bytes(data)
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
        with open(src, "rb") as f:
            data = f.read()
        path = import_storage.save_original(job_id, data, ext)
        await import_jobs.update_job(
            job_id, original_path=str(path),
            file_sha256=import_storage.sha256_bytes(data), status="uploaded",
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
    job_id = await import_jobs.create_job(
        fmt, original_path="", options={"upload": {"size": int(payload.size or 0), "ext": ext.lstrip('.')}},
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
    """Append one chunk at the byte offset given in the `Upload-Offset` header."""
    from novelwiki.importer import storage as import_storage
    job = await _require_own_job(job_id, user)
    if job["status"] != "receiving":
        raise HTTPException(status_code=409, detail="Upload session is not open.")
    up = (job.get("options") or {}).get("upload") or {}
    ext = up.get("ext", job["format"])
    try:
        offset = int(request.headers.get("Upload-Offset", "0"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Upload-Offset header.")
    data = await request.body()
    if len(data) > settings.UPLOAD_CHUNK_MAX_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Chunk too large.")
    new_offset = import_storage.write_chunk(job_id, ext, offset, data)
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
    sha, size = import_storage.finalize_upload(job_id, ext)
    declared = int(up.get("size") or 0)
    if declared and size != declared:
        raise HTTPException(status_code=400,
                            detail=f"Upload incomplete: have {size} bytes, expected {declared}.")
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
