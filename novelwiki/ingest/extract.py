import json
import logging
import asyncio
import asyncpg
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.db.queries import clear_caches
from novelwiki.agent.llm_client import call_chat_completion
from novelwiki.ingest.link import resolve_entity
from novelwiki.agent.prompts import EXTRACTION_SYSTEM, EXTRACTION_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUMMARY_SYSTEM = """You are a professional novel editor keeping a running 'story-so-far' summary.
Given the previous running summary and the text of the current chapter, produce an updated, highly structured running summary.
Rules:
1. Maintain strict chronological order.
2. Only include facts and developments revealed up to the current chapter. Never anticipate the future.
3. Keep the summary concise, focused, and under 1500 tokens. Highlight key character locations, faction alliances, item acquisitions, and secrets.
"""

SUMMARY_USER = """Previous Running Summary:
{prev_summary}

--- CURRENT CHAPTER ---
Title: {title}
Text:
{text}

Output the updated running summary.
"""


def _clean_chunk_ids(raw, valid_set: set[int], fallback: list[int]) -> list[int]:
    """Keep only model-supplied chunk ids that genuinely belong to this chapter.
    Falls back to all of the chapter's chunk ids so provenance is never empty
    (and, by construction, every id is from chapter <= N — Invariant 8)."""
    if not raw:
        return list(fallback)
    ids = []
    for x in raw:
        try:
            xi = int(x)
        except (TypeError, ValueError):
            continue
        if xi in valid_set and xi not in ids:
            ids.append(xi)
    return ids if ids else list(fallback)


async def get_running_summary(chapter: float, conn: asyncpg.Connection) -> str:
    """Gets the running summary through the previous chapter, ordered ascending."""
    row = await conn.fetchrow(
        "SELECT running_summary FROM extraction_state WHERE chapter < $1 ORDER BY chapter DESC LIMIT 1;",
        chapter
    )
    if row and row["running_summary"]:
        return row["running_summary"]
    return "No summary yet. The story is just beginning."


async def get_known_entities_roster(chapter: float, conn: asyncpg.Connection) -> str:
    """Assembles a compact roster of entities known BEFORE this chapter."""
    rows = await conn.fetch(
        """
        SELECT id, canonical_name, type, description
        FROM entities
        WHERE first_seen_chapter < $1
        ORDER BY id ASC;
        """,
        chapter
    )
    if not rows:
        return "No entities recorded yet."
    roster_lines = []
    for r in rows:
        desc = r["description"] or "No description yet."
        roster_lines.append(f"- ID {r['id']}: {r['canonical_name']} ({r['type']}) - {desc}")
    return "\n".join(roster_lines)


async def _load_chapter_chunks(chapter_number: float, conn: asyncpg.Connection):
    """Returns (marked_text, valid_chunk_ids_set, all_chunk_ids_list) for a chapter.
    The marked text prefixes each passage with `[chunk <id>]` so the extractor can
    attach per-item provenance."""
    chunk_rows = await conn.fetch(
        "SELECT id, chunk_index, text FROM chunks WHERE chapter = $1 ORDER BY chunk_index ASC;",
        chapter_number
    )
    all_ids = [int(r["id"]) for r in chunk_rows]
    valid = set(all_ids)
    marked = "\n\n".join(f"[chunk {int(r['id'])}]\n{r['text']}" for r in chunk_rows)
    return marked, valid, all_ids


async def extract_knowledge_for_chapter(chapter_number: float, force: bool = False):
    """
    Extracts structured knowledge from chapter_number in a forward-only transaction.
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        # Check if already processed
        processed = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM extraction_state WHERE chapter = $1);",
            chapter_number
        )
        if processed and not force:
            logger.info(f"Chapter {chapter_number} already extracted. Skipping.")
            return

        logger.info(f"--- Starting Forward-Only Extraction for Chapter {chapter_number} ---")
        # Invalidate affected cache entries
        await clear_caches(conn, chapter_number=chapter_number)

        # Load chapter info
        chapter = await conn.fetchrow(
            "SELECT title, clean_text FROM chapters WHERE number = $1;",
            chapter_number
        )
        if not chapter:
            logger.error(f"Chapter {chapter_number} not found in DB.")
            return

        # Build chunk-marked text + provenance id set (Invariant 8).
        marked_text, valid_chunk_ids, all_chunk_ids = await _load_chapter_chunks(chapter_number, conn)
        if not all_chunk_ids:
            logger.warning(
                f"Chapter {chapter_number} has no chunks; run `chunk` before `extract` for provenance. "
                f"Proceeding with raw text and empty provenance."
            )
            extraction_body = chapter["clean_text"]
        else:
            extraction_body = marked_text

        # 1. Compile forward context
        prev_summary = await get_running_summary(chapter_number, conn)
        roster = await get_known_entities_roster(chapter_number, conn)

        running_summary_context = (
            f"Running Story Summary so far:\n{prev_summary}\n\n"
            f"Active Roster of Known Entities:\n{roster}"
        )

        # 2. Invoke Flash for structured JSON extraction
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": EXTRACTION_USER.format(
                    running_summary=running_summary_context,
                    chapter_number=chapter_number,
                    chapter_title=chapter["title"],
                    chapter_text=extraction_body
                )
            }
        ]

        try:
            logger.info(f"Calling Flash extraction model for Chapter {chapter_number}...")
            resp = await call_chat_completion(
                model=settings.MODEL_FLASH,
                messages=messages,
                temperature=0.0
            )
            clean_resp = resp.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_resp)
        except Exception as e:
            logger.error(f"Flash JSON extraction failed for Chapter {chapter_number}: {e}")
            raise e

        # 3. Resolve & Link mentions to entities (Inside a transaction)
        async with conn.transaction():
            local_ref_to_id = {}

            # Map mentions first (with descriptions for new-entity creation)
            for mention in data.get("mentions", []):
                ref = mention.get("entity_ref")
                surface = mention.get("surface_form") or ref
                etype = mention.get("type")
                mdesc = mention.get("description")

                # Locate surface form context snippet for disambiguation
                context_snippet = ""
                if surface:
                    context_idx = chapter["clean_text"].lower().find(surface.lower())
                    if context_idx != -1:
                        start = max(0, context_idx - 100)
                        end = min(len(chapter["clean_text"]), context_idx + len(surface) + 100)
                        context_snippet = chapter["clean_text"][start:end]

                entity_id = await resolve_entity(
                    mention=ref or surface,
                    entity_type=etype,
                    chapter=chapter_number,
                    context=context_snippet,
                    conn=conn,
                    description=mdesc,
                )
                if ref:
                    local_ref_to_id[ref] = entity_id

            async def get_entity_id(ref_name: str, fallback_type: str = "concept") -> int:
                if ref_name in local_ref_to_id:
                    return local_ref_to_id[ref_name]
                logger.info(f"Ref '{ref_name}' was not explicitly mentioned. Resolving dynamically...")
                entity_id = await resolve_entity(ref_name, fallback_type, chapter_number, ref_name, conn)
                local_ref_to_id[ref_name] = entity_id
                return entity_id

            # 4. Insert entity facts (per-item provenance)
            for fact in data.get("facts", []):
                ref = fact.get("entity_ref")
                if not ref:
                    continue
                fid = await get_entity_id(ref)
                src_ids = _clean_chunk_ids(fact.get("source_chunk_ids"), valid_chunk_ids, all_chunk_ids)
                await conn.execute(
                    """
                    INSERT INTO entity_facts (entity_id, chapter, fact_type, content, source_chunk_ids)
                    VALUES ($1, $2, $3, $4, $5);
                    """,
                    fid, chapter_number, fact.get("fact_type"), fact.get("content"), src_ids
                )

            # 5. Insert relationships (per-item provenance)
            for rel in data.get("relationships", []):
                if not rel.get("source_ref") or not rel.get("target_ref"):
                    continue
                src_id = await get_entity_id(rel.get("source_ref"), "character")
                tgt_id = await get_entity_id(rel.get("target_ref"), "character")
                src_ids = _clean_chunk_ids(rel.get("source_chunk_ids"), valid_chunk_ids, all_chunk_ids)
                await conn.execute(
                    """
                    INSERT INTO relationships (source_id, target_id, chapter, relation_type, directed, content, source_chunk_ids)
                    VALUES ($1, $2, $3, $4, $5, $6, $7);
                    """,
                    src_id, tgt_id, chapter_number, rel.get("relation_type"),
                    rel.get("directed", True), rel.get("content"), src_ids
                )

            # 6. Insert events (per-item provenance)
            for ev in data.get("events", []):
                participants = []
                for p in ev.get("participant_refs", []):
                    if p:
                        participants.append(await get_entity_id(p, "character"))
                loc_ref = ev.get("location_ref")
                loc_id = await get_entity_id(loc_ref, "location") if loc_ref else None
                src_ids = _clean_chunk_ids(ev.get("source_chunk_ids"), valid_chunk_ids, all_chunk_ids)
                await conn.execute(
                    """
                    INSERT INTO events (chapter, description, participants, location_id, significance, source_chunk_ids)
                    VALUES ($1, $2, $3, $4, $5, $6);
                    """,
                    chapter_number, ev.get("description"), participants, loc_id,
                    ev.get("significance"), src_ids
                )

            # 7. Insert identity_links (masked personas)
            for reveal in data.get("identity_reveals", []):
                if not reveal.get("persona_ref") or not reveal.get("true_entity_ref"):
                    continue
                persona_id = await get_entity_id(reveal.get("persona_ref"), "character")
                true_id = await get_entity_id(reveal.get("true_entity_ref"), "character")
                if persona_id == true_id:
                    continue
                await conn.execute(
                    """
                    INSERT INTO identity_links (entity_a, entity_b, revealed_at_chapter, note)
                    VALUES ($1, $2, $3, $4);
                    """,
                    persona_id, true_id, chapter_number, reveal.get("note")
                )
                logger.info(f"Recorded Identity Reveal at Chapter {chapter_number}: Entity {persona_id} = Entity {true_id}")

            # 8. Insert new aliases
            for alias_item in data.get("new_aliases", []):
                if not alias_item.get("entity_ref") or not alias_item.get("alias"):
                    continue
                ent_id = await get_entity_id(alias_item.get("entity_ref"))
                alias_name = alias_item.get("alias")
                is_rev = alias_item.get("is_reveal", False)
                reveal_ch = chapter_number if is_rev else 0.0
                await conn.execute(
                    """
                    INSERT INTO entity_aliases (entity_id, alias, revealed_at_chapter)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (entity_id, alias) DO UPDATE
                    SET revealed_at_chapter = LEAST(entity_aliases.revealed_at_chapter, EXCLUDED.revealed_at_chapter);
                    """,
                    ent_id, alias_name, reveal_ch
                )

            # 9. Update running summary using Flash
            summary_messages = [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {
                    "role": "user",
                    "content": SUMMARY_USER.format(
                        prev_summary=prev_summary,
                        title=chapter["title"],
                        text=chapter["clean_text"][:8000]  # bound context for the summary call
                    )
                }
            ]

            logger.info(f"Generating updated running summary through Chapter {chapter_number}...")
            new_summary = await call_chat_completion(
                model=settings.MODEL_FLASH,
                messages=summary_messages,
                temperature=0.3
            )

            # Save state
            await conn.execute(
                """
                INSERT INTO extraction_state (chapter, running_summary, processed_at)
                VALUES ($1, $2, now())
                ON CONFLICT (chapter) DO UPDATE
                SET running_summary = EXCLUDED.running_summary, processed_at = now();
                """,
                chapter_number, new_summary
            )

        logger.info(f"--- Chapter {chapter_number} Extraction Complete ---")


async def extract_all_chapters(
    force: bool = False,
    from_chapter: float | None = None,
    to_chapter: float | None = None,
):
    """Processes chapters in strict ascending order (Invariant 2), optionally limited
    to a [from_chapter, to_chapter] range so the prompt can be iterated on the first
    ~50 chapters before committing to the full paid run."""
    pool = await get_db_pool()
    conditions = []
    args: list = []
    if from_chapter is not None:
        args.append(from_chapter)
        conditions.append(f"number >= ${len(args)}")
    if to_chapter is not None:
        args.append(to_chapter)
        conditions.append(f"number <= ${len(args)}")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT number FROM chapters{where} ORDER BY number ASC;", *args)

    for row in rows:
        await extract_knowledge_for_chapter(float(row["number"]), force=force)


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv

    async def main():
        await extract_all_chapters(force=force)
        await close_db_pool()

    asyncio.run(main())
