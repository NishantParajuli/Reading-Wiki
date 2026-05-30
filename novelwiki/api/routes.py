import logging
import json
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.scraper.runner import scrape_novel
from novelwiki.ingest.chunk import chunk_all_chapters
from novelwiki.ingest.embed import embed_missing_chunks
from novelwiki.ingest.extract import extract_all_chapters
from novelwiki.ingest.link import merge_entities
from novelwiki.retrieval.bm25 import bm25_manager
from novelwiki.retrieval.tools import (
    resolve_entity, get_entity_profile, get_relationships, get_timeline, list_entities
)
from novelwiki.agent.orchestrator import answer_question
from novelwiki.agent.llm_client import call_chat_completion
from novelwiki.agent.prompts import WIKI_PROFILE_SYNTHESIS_SYSTEM, WIKI_PROFILE_SYNTHESIS_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# ── API Models ────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str
    chapter_ceiling: float

class Citation(BaseModel):
    kind: str
    id: int
    chapter: float
    snippet: str

class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    evidence_ids: dict

# Admin Trigger Payloads
class ScrapePayload(BaseModel):
    start_url: str
    force: bool = False
    max_chapters: int | None = None

class RangePayload(BaseModel):
    force: bool = False
    from_chapter: float | None = None
    to_chapter: float | None = None

class EmbedPayload(BaseModel):
    from_chapter: float | None = None
    to_chapter: float | None = None

class MergePayload(BaseModel):
    keep_id: int
    drop_id: int

# ── Endpoints ─────────────────────────────────────────────────────────────

@router.post("/ask", response_model=AskResponse)
async def ask_question(req: AskRequest):
    """
    Agentic Q&A: planning, reasoning, distilling, synthesis and grounding verification.
    """
    try:
        if not bm25_manager.corpus:
            await bm25_manager.load_or_build_index()

        result = await answer_question(req.question, req.chapter_ceiling)
        return AskResponse(
            answer=result["answer"],
            citations=[Citation(**c) for c in result["citations"]],
            evidence_ids=result["evidence_ids"],
        )
    except Exception as e:
        logger.error(f"Agentic Q&A error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Meta ──────────────────────────────────────────────────────────────────

@router.get("/meta/chapters")
async def api_meta_chapters():
    """Returns the chapter span available, so the UI can bound the ceiling control."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS count, MIN(number) AS min_chapter, MAX(number) AS max_chapter FROM chapters;"
        )
    return {
        "count": int(row["count"]),
        "min_chapter": float(row["min_chapter"]) if row["min_chapter"] is not None else None,
        "max_chapter": float(row["max_chapter"]) if row["max_chapter"] is not None else None,
    }


# ── Structured Wiki Endpoints ─────────────────────────────────────────────

@router.get("/entities")
async def api_list_entities(ceiling: float, type: str | None = None, q: str | None = None):
    """Lists all entities discovered at or before the ceiling."""
    try:
        return await list_entities(chapter_ceiling=ceiling, entity_type=type, name_query=q)
    except Exception as e:
        logger.error(f"Error listing entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/entity/resolve")
async def api_resolve_entity(name: str, ceiling: float):
    """Resolves an entity name or alias below the chapter ceiling."""
    try:
        return await resolve_entity(name=name, chapter_ceiling=ceiling)
    except Exception as e:
        logger.error(f"Error resolving entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/entity/{entity_id}")
async def api_get_entity_profile(entity_id: int, ceiling: float):
    """Gets the structured profile of an entity at the ceiling, using the wiki_cache fast path."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            cached_row = await conn.fetchrow(
                "SELECT rendered_md FROM wiki_cache WHERE entity_id = $1 AND chapter_ceiling = $2;",
                entity_id, ceiling
            )

        profile = await get_entity_profile(entity_id=entity_id, chapter_ceiling=ceiling)
        if not profile:
            raise HTTPException(status_code=404, detail="Entity not found or not yet visible.")

        if cached_row:
            logger.info(f"Wiki cache hit for entity {entity_id} at ceiling {ceiling}")
            profile["rendered_md"] = cached_row["rendered_md"]
            return profile

        logger.info(f"Wiki cache miss for entity {entity_id} at ceiling {ceiling}. Synthesizing...")

        canonical_name = profile["canonical_name"]
        aliases = ", ".join(profile["aliases"]) if profile["aliases"] else "None"
        facts_str = "\n".join([
            f"- [Fact {f['id']}, Ch {f['chapter']}] ({f['fact_type']}): {f['content']}"
            for f in profile["facts"]
        ]) if profile["facts"] else "No facts recorded."

        rels = await get_relationships(entity_id, ceiling)
        rels_str = "\n".join([
            f"- [Rel {r['id']}, Ch {r['chapter']}] {r['source_name']} ({r['relation_type']}) {r['target_name']}: {r['content'] or ''}"
            for r in rels
        ]) if rels else "No relationships recorded."

        messages = [
            {"role": "system", "content": WIKI_PROFILE_SYNTHESIS_SYSTEM.format(chapter_ceiling=ceiling)},
            {
                "role": "user",
                "content": WIKI_PROFILE_SYNTHESIS_USER.format(
                    canonical_name=canonical_name,
                    type=profile["type"],
                    chapter_ceiling=ceiling,
                    aliases=aliases,
                    facts=facts_str,
                    relationships=rels_str
                )
            }
        ]

        rendered_md = await call_chat_completion(
            model=settings.MODEL_PRO,
            messages=messages,
            temperature=0.0
        )

        evidence_ids = {
            "fact_ids": [f["id"] for f in profile["facts"]],
            "rel_ids": [r["id"] for r in rels],
        }
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO wiki_cache (entity_id, chapter_ceiling, rendered_md, model, evidence_ids)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (entity_id, chapter_ceiling) DO UPDATE
                SET rendered_md = EXCLUDED.rendered_md, model = EXCLUDED.model, evidence_ids = EXCLUDED.evidence_ids;
                """,
                entity_id, ceiling, rendered_md, settings.MODEL_PRO, json.dumps(evidence_ids)
            )

        profile["rendered_md"] = rendered_md
        return profile
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/entity/{entity_id}/relationships")
async def api_get_relationships(entity_id: int, ceiling: float, other_id: int | None = None):
    """Gets the relationship connections or developments of an entity below the ceiling."""
    try:
        return await get_relationships(entity_id=entity_id, chapter_ceiling=ceiling, other_id=other_id)
    except Exception as e:
        logger.error(f"Error fetching relationships: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/entity/{entity_id}/timeline")
async def api_get_timeline(entity_id: int, ceiling: float):
    """Chronologically aggregates all facts and events of an entity below the ceiling."""
    try:
        return await get_timeline(entity_id=entity_id, chapter_ceiling=ceiling)
    except Exception as e:
        logger.error(f"Error fetching timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ── Admin Ingestion Routes ────────────────────────────────────────────────

@router.post("/admin/scrape")
async def trigger_scrape(payload: ScrapePayload, bg_tasks: BackgroundTasks):
    """Triggers the sequential novel scraper in the background."""
    bg_tasks.add_task(
        scrape_novel,
        payload.start_url,
        force=payload.force,
        max_chapters=payload.max_chapters
    )
    return {"status": "success", "message": "Scraper job scheduled in background."}

@router.post("/admin/chunk")
async def trigger_chunking(payload: RangePayload, bg_tasks: BackgroundTasks):
    """Triggers chunking of chapters in the database (optionally within a range)."""
    bg_tasks.add_task(
        chunk_all_chapters,
        force=payload.force,
        from_chapter=payload.from_chapter,
        to_chapter=payload.to_chapter,
    )
    return {"status": "success", "message": "Chunking job scheduled in background."}

@router.post("/admin/embed")
async def trigger_embeddings(payload: EmbedPayload, bg_tasks: BackgroundTasks):
    """Triggers generation of embeddings for missing chunks (optionally within a range)."""
    bg_tasks.add_task(
        embed_missing_chunks,
        from_chapter=payload.from_chapter,
        to_chapter=payload.to_chapter,
    )
    return {"status": "success", "message": "Embedding job scheduled in background."}

@router.post("/admin/rebuild-bm25")
async def rebuild_bm25():
    """Forces rebuild + persist of the sparse BM25 index."""
    await bm25_manager.rebuild()
    return {"status": "success", "message": "BM25 index rebuilt and persisted."}

@router.post("/admin/extract")
async def trigger_extraction(payload: RangePayload, bg_tasks: BackgroundTasks):
    """Triggers forward-only entity/fact extraction (optionally within a range)."""
    bg_tasks.add_task(
        extract_all_chapters,
        force=payload.force,
        from_chapter=payload.from_chapter,
        to_chapter=payload.to_chapter,
    )
    return {"status": "success", "message": "Extraction job scheduled in background."}

@router.post("/admin/merge-entities")
async def trigger_merge(payload: MergePayload):
    """Merges a duplicate entity (drop_id) into keep_id (extraction-error dedup)."""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await merge_entities(payload.keep_id, payload.drop_id, conn)
        return {"status": "success", "message": f"Entity {payload.drop_id} merged into {payload.keep_id}."}
    except Exception as e:
        logger.error(f"Error merging entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))
