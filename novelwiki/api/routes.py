import logging
import json
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
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
async def api_list_novels():
    """The library grid: each novel with chapter span + reading progress."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id, n.title, n.author, n.cover_url, n.description, n.codex_enabled,
                   n.shelf, n.status_tags,
                   COUNT(c.number) AS chapter_count,
                   MIN(c.number) AS min_chapter, MAX(c.number) AS max_chapter,
                   p.last_chapter, p.max_chapter_read,
                   (SELECT bool_or(s.is_raw)     FROM sources s WHERE s.novel_id = n.id) AS has_raw,
                   (SELECT bool_or(NOT s.is_raw)  FROM sources s WHERE s.novel_id = n.id) AS has_eng
            FROM novels n
            LEFT JOIN chapters c ON c.novel_id = n.id
            LEFT JOIN reading_progress p ON p.novel_id = n.id
            GROUP BY n.id, p.last_chapter, p.max_chapter_read
            ORDER BY n.updated_at DESC NULLS LAST, n.id DESC;
            """
        )
    return [
        {
            "id": int(r["id"]),
            "title": r["title"],
            "author": r["author"],
            "cover_url": r["cover_url"],
            "description": r["description"],
            "codex_enabled": r["codex_enabled"],
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
async def api_create_novel(payload: NovelCreate):
    """Create a novel and (optionally) its first source."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            novel_id = await conn.fetchval(
                """
                INSERT INTO novels (title, author, description, cover_url, original_language, codex_enabled)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING id;
                """,
                payload.title, payload.author, payload.description, payload.cover_url,
                payload.original_language, payload.codex_enabled,
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
async def api_get_novel(novel_id: int):
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
        progress = await conn.fetchrow("SELECT * FROM reading_progress WHERE novel_id = $1;", novel_id)
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
        "shelf": novel["shelf"],
        "status_tags": list(novel["status_tags"] or []),
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
async def api_update_novel(novel_id: int, payload: NovelUpdate):
    """Edit novel metadata (title, author, description, cover, codex toggle, shelf, tags)."""
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return {"status": "noop"}
    # Normalize the user-curation fields: blank shelf clears it; tags are whitelisted.
    if "shelf" in fields:
        shelf = (fields["shelf"] or "").strip().lower()
        if shelf and shelf not in SHELVES:
            raise HTTPException(status_code=422, detail=f"Unknown shelf '{shelf}'.")
        fields["shelf"] = shelf or None
    if "status_tags" in fields:
        tags = [t.strip().lower() for t in (fields["status_tags"] or [])]
        fields["status_tags"] = [t for t in dict.fromkeys(tags) if t in STATUS_TAGS]
    sets, args = [], []
    for k, v in fields.items():
        args.append(v)
        sets.append(f"{k} = ${len(args)}")
    args.append(novel_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE novels SET {', '.join(sets)}, updated_at = now() WHERE id = ${len(args)} RETURNING id;",
            *args,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Novel not found.")
    return {"status": "success"}


@router.delete("/novels/{novel_id}")
async def api_delete_novel(novel_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM novels WHERE id = $1;", novel_id)
    return {"status": "success"}


@router.post("/novels/{novel_id}/sources")
async def api_add_source(novel_id: int, payload: SourceCreate):
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
async def api_update_source(novel_id: int, source_id: int, payload: SourceUpdate):
    """Edits an existing source. Changing `chapter_offset` also renumbers that source's
    already-scraped chapters onto the new global numbering (e.g. set -1 when a raw source
    is one chapter ahead of the translation), so the fix is immediate — no re-scrape."""
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
async def api_list_chapters(novel_id: int):
    """The table of contents for the reader."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT number, title, language, is_translated, translation_status,
                   (content IS NOT NULL) AS has_content, word_count
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
        }
        for r in rows
    ]


@router.get("/novels/{novel_id}/chapter/{number}")
async def api_get_chapter(novel_id: int, number: float, bg_tasks: BackgroundTasks):
    """Returns one chapter's readable content for the reader, plus prev/next numbers.
    Raw chapters are translated on demand here (and the next few are prefetched in the
    background), so the reader always gets English text — keyed off `translation_status`."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT number, title, content, (original_text IS NOT NULL) AS has_original,
                   language, is_translated, translation_status
            FROM chapters WHERE novel_id = $1 AND number = $2;
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
    # On-demand translation for a raw chapter that hasn't been translated yet.
    if content is None and row["has_original"]:
        result = await translate_chapter(novel_id, number)
        content = result.get("content")
        status = result.get("status")
        is_translated = status == "done"
        # Warm the next few chapters so reading flows without waiting at each boundary.
        bg_tasks.add_task(prefetch_translations, novel_id, number, settings.TRANSLATE_PREFETCH)

    return {
        "number": float(row["number"]),
        "title": row["title"],
        "content": content,
        "language": row["language"],
        "is_translated": is_translated,
        "translation_status": status,
        "prev": float(prev_num) if prev_num is not None else None,
        "next": float(next_num) if next_num is not None else None,
    }


# ── Reading progress ──────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/progress")
async def api_get_progress(novel_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM reading_progress WHERE novel_id = $1;", novel_id)
    if not row:
        return {"last_chapter": None, "max_chapter_read": None, "scroll_pct": 0}
    return {
        "last_chapter": float(row["last_chapter"]) if row["last_chapter"] is not None else None,
        "max_chapter_read": float(row["max_chapter_read"]) if row["max_chapter_read"] is not None else None,
        "scroll_pct": float(row["scroll_pct"] or 0),
    }


@router.put("/novels/{novel_id}/progress")
async def api_set_progress(novel_id: int, payload: ProgressUpdate):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO reading_progress (novel_id, last_chapter, max_chapter_read, scroll_pct, updated_at)
            VALUES ($1, $2, $2, $3, now())
            ON CONFLICT (novel_id) DO UPDATE SET
                last_chapter = EXCLUDED.last_chapter,
                max_chapter_read = GREATEST(COALESCE(reading_progress.max_chapter_read, 0), EXCLUDED.last_chapter),
                scroll_pct = EXCLUDED.scroll_pct,
                updated_at = now();
            """,
            novel_id, payload.last_chapter, payload.scroll_pct,
        )
    return {"status": "success"}


# ── Bookmarks ─────────────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/bookmarks")
async def api_list_bookmarks(novel_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, chapter, note, created_at FROM bookmarks WHERE novel_id = $1 ORDER BY chapter ASC;",
            novel_id,
        )
    return [
        {"id": int(r["id"]), "chapter": float(r["chapter"]), "note": r["note"],
         "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]


@router.post("/novels/{novel_id}/bookmarks")
async def api_add_bookmark(novel_id: int, payload: BookmarkCreate):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        bid = await conn.fetchval(
            "INSERT INTO bookmarks (novel_id, chapter, note) VALUES ($1, $2, $3) RETURNING id;",
            novel_id, payload.chapter, payload.note,
        )
    return {"id": int(bid)}


@router.delete("/novels/{novel_id}/bookmarks/{bookmark_id}")
async def api_delete_bookmark(novel_id: int, bookmark_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM bookmarks WHERE id = $1 AND novel_id = $2;", bookmark_id, novel_id)
    return {"status": "success"}


# ── Scraping ──────────────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/scrape")
async def api_scrape(novel_id: int, payload: ScrapeTrigger, bg_tasks: BackgroundTasks):
    """Kicks off scraping in the background. Targets one source if source_id is given,
    else every source of the novel."""
    if payload.source_id is not None:
        bg_tasks.add_task(scrape_source, payload.source_id, force=payload.force, max_chapters=payload.max_chapters)
    else:
        bg_tasks.add_task(scrape_novel, novel_id, force=payload.force, max_chapters=payload.max_chapters)
    return {"status": "success", "message": "Scrape job scheduled in background."}


# ── Translation + glossary ────────────────────────────────────────────────

@router.post("/novels/{novel_id}/translate")
async def api_translate(novel_id: int, payload: TranslateTrigger, bg_tasks: BackgroundTasks):
    """Translate raw chapters in a range in the background (manual batch; reading
    itself uses on-demand + prefetch). Optionally seed the glossary from the codex first."""
    async def _job():
        if payload.seed_from_codex:
            await seed_glossary_from_entities(novel_id)
        await translate_range(novel_id, payload.from_chapter, payload.to_chapter, payload.force)
    bg_tasks.add_task(_job)
    return {"status": "success", "message": "Translation job scheduled in background."}


@router.post("/novels/{novel_id}/glossary/seed")
async def api_seed_glossary(novel_id: int):
    """Seed the glossary's English spellings from the established codex entities."""
    n = await seed_glossary_from_entities(novel_id)
    return {"status": "success", "seeded": n}


@router.get("/novels/{novel_id}/glossary")
async def api_list_glossary(novel_id: int):
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
async def api_upsert_glossary(novel_id: int, payload: GlossaryUpsert):
    """Add or update a glossary term (manual edits win and are typically locked)."""
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
async def api_delete_glossary(novel_id: int, term_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM translation_glossary WHERE id = $1 AND novel_id = $2;", term_id, novel_id)
    return {"status": "success"}


# ── Codex: meta / stats ───────────────────────────────────────────────────

@router.get("/novels/{novel_id}/meta")
async def api_meta_chapters(novel_id: int):
    """Chapter span + display title/blurb so the codex ceiling control can be bounded."""
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
async def api_meta_stats(novel_id: int, ceiling: float):
    """Spoiler-safe aggregate stats for the codex home surface (all bounded by ceiling)."""
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
async def api_list_entities(novel_id: int, ceiling: float, type: str | None = None, q: str | None = None):
    try:
        return await list_entities(novel_id, chapter_ceiling=ceiling, entity_type=type, name_query=q)
    except Exception as e:
        logger.error(f"Error listing entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/resolve")
async def api_resolve_entity(novel_id: int, name: str, ceiling: float):
    try:
        return await resolve_entity(novel_id, name=name, chapter_ceiling=ceiling)
    except Exception as e:
        logger.error(f"Error resolving entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}")
async def api_get_entity_profile(novel_id: int, entity_id: int, ceiling: float):
    """Structured profile at the ceiling, using the wiki_cache fast path."""
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
async def api_get_relationships(novel_id: int, entity_id: int, ceiling: float, other_id: int | None = None):
    try:
        return await get_relationships(novel_id, entity_id=entity_id, chapter_ceiling=ceiling, other_id=other_id)
    except Exception as e:
        logger.error(f"Error fetching relationships: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}/timeline")
async def api_get_timeline(novel_id: int, entity_id: int, ceiling: float):
    try:
        return await get_timeline(novel_id, entity_id=entity_id, chapter_ceiling=ceiling)
    except Exception as e:
        logger.error(f"Error fetching timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/novels/{novel_id}/entity/{entity_id}/identities")
async def api_get_identities(novel_id: int, entity_id: int, ceiling: float):
    try:
        return await get_identity_links(novel_id, entity_id=entity_id, chapter_ceiling=ceiling)
    except Exception as e:
        logger.error(f"Error fetching identity links: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Codex: Q&A + build ────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/ask", response_model=AskResponse)
async def ask_question(novel_id: int, req: AskRequest):
    """Agentic spoiler-safe Q&A scoped to one novel."""
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
async def api_codex_build(novel_id: int, payload: CodexBuild, bg_tasks: BackgroundTasks):
    """Builds (or rebuilds) the spoiler-safe codex for a novel in the background."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE novels SET codex_enabled = TRUE WHERE id = $1;", novel_id)
    bg_tasks.add_task(_build_codex, novel_id, payload.force, payload.from_chapter, payload.to_chapter)
    return {"status": "success", "message": "Codex build scheduled in background."}


@router.post("/novels/{novel_id}/merge-entities")
async def trigger_merge(novel_id: int, payload: MergePayload):
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await merge_entities(novel_id, payload.keep_id, payload.drop_id, conn)
        return {"status": "success", "message": f"Entity {payload.drop_id} merged into {payload.keep_id}."}
    except Exception as e:
        logger.error(f"Error merging entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))
