import json
import logging
import asyncio
import asyncpg
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.db.queries import clear_caches
from novelwiki.agent.llm_client import call_chat_completion
from novelwiki.ingest.link import resolve_entity
from novelwiki.agent.prompts import (
    EXTRACTION_SYSTEM,
    EXTRACTION_USER,
    EXTRACTION_VERIFY_SYSTEM,
    EXTRACTION_VERIFY_USER,
)

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

# Top-level keys of the extraction schema (see prompts.EXTRACTION_SYSTEM).
EXTRACTION_KEYS = ("mentions", "facts", "relationships", "events", "identity_reveals", "new_aliases")


def _parse_json_object(raw: str):
    """Parse a model response into a Python object, tolerating markdown code fences
    and minor JSON breakage via json_repair (when installed). Raises on hard failure
    so the caller can re-ask rather than silently dropping a chapter's knowledge."""
    clean = (raw or "").strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except Exception:
        try:
            import json_repair
        except ImportError:
            raise
        return json_repair.loads(clean)


def _coerce_extraction(data) -> dict:
    """Normalize a parsed extraction payload to the expected schema: a dict whose
    every expected key is a list. Raises ValueError if the payload is not a JSON
    object at all, so a garbled response triggers a retry instead of silent loss."""
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return {key: (data[key] if isinstance(data.get(key), list) else []) for key in EXTRACTION_KEYS}


async def _call_and_parse(messages: list[dict], label: str, temperature: float = 0.0) -> dict:
    """Invoke Flash, parse + coerce the JSON, and re-ask ONCE (with a small temperature
    nudge so a deterministic bad output isn't simply reproduced) if the payload is
    unusable. Raises on a second failure rather than corrupting the knowledge base."""
    raw = await call_chat_completion(model=settings.MODEL_FLASH, messages=messages, temperature=temperature)
    try:
        return _coerce_extraction(_parse_json_object(raw))
    except Exception as first_err:
        retry_temp = max(temperature, 0.3)
        logger.warning(f"{label}: JSON parse/shape failed ({first_err}); re-asking once at temp {retry_temp}...")
        raw_retry = await call_chat_completion(model=settings.MODEL_FLASH, messages=messages, temperature=retry_temp)
        try:
            return _coerce_extraction(_parse_json_object(raw_retry))
        except Exception as second_err:
            logger.error(f"{label}: extraction still unusable after retry: {second_err}")
            raise


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


async def get_running_summary(novel_id: int, chapter: float, conn: asyncpg.Connection) -> str:
    """Gets the running summary through the previous chapter, ordered ascending."""
    row = await conn.fetchrow(
        "SELECT running_summary FROM extraction_state WHERE chapter < $1 AND novel_id = $2 ORDER BY chapter DESC LIMIT 1;",
        chapter, novel_id
    )
    if row and row["running_summary"]:
        return row["running_summary"]
    return "No summary yet. The story is just beginning."


async def get_known_entities_roster(novel_id: int, chapter: float, conn: asyncpg.Connection) -> str:
    """Assembles a compact roster of entities known BEFORE this chapter, using the
    freshest spoiler-safe description (latest one observed in a chapter < this one,
    falling back to the first-seen blurb)."""
    rows = await conn.fetch(
        """
        SELECT e.id, e.canonical_name, e.type,
               COALESCE(d.description, e.description) AS description
        FROM entities e
        LEFT JOIN LATERAL (
            SELECT description
            FROM entity_descriptions ed
            WHERE ed.entity_id = e.id AND ed.chapter < $1
            ORDER BY ed.chapter DESC
            LIMIT 1
        ) d ON TRUE
        WHERE e.first_seen_chapter < $1 AND e.novel_id = $2
        ORDER BY e.id ASC;
        """,
        chapter, novel_id
    )
    if not rows:
        return "No entities recorded yet."
    roster_lines = []
    for r in rows:
        desc = r["description"] or "No description yet."
        roster_lines.append(f"- ID {r['id']}: {r['canonical_name']} ({r['type']}) - {desc}")
    return "\n".join(roster_lines)


async def _load_chapter_chunks(novel_id: int, chapter_number: float, conn: asyncpg.Connection):
    """Returns (marked_text, valid_chunk_ids_set, all_chunk_ids_list) for a chapter.
    The marked text prefixes each passage with `[chunk <id>]` so the extractor can
    attach per-item provenance."""
    chunk_rows = await conn.fetch(
        "SELECT id, chunk_index, text FROM chunks WHERE chapter = $1 AND novel_id = $2 ORDER BY chunk_index ASC;",
        chapter_number, novel_id
    )
    all_ids = [int(r["id"]) for r in chunk_rows]
    valid = set(all_ids)
    marked = "\n\n".join(f"[chunk {int(r['id'])}]\n{r['text']}" for r in chunk_rows)
    return marked, valid, all_ids


async def extract_knowledge_for_chapter(novel_id: int, chapter_number: float, force: bool = False):
    """
    Extracts structured knowledge from chapter_number in a forward-only transaction.
    """
    pool = await get_db_pool()

    async with pool.acquire() as conn:
        # Check if already processed
        processed = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM extraction_state WHERE chapter = $1 AND novel_id = $2);",
            chapter_number, novel_id
        )
        if processed and not force:
            logger.info(f"Chapter {chapter_number} already extracted. Skipping.")
            return

        logger.info(f"--- Starting Forward-Only Extraction for Chapter {chapter_number} ---")
        # Invalidate affected cache entries
        await clear_caches(conn, novel_id=novel_id, chapter_number=chapter_number)

        # Load chapter info
        chapter = await conn.fetchrow(
            "SELECT title, content FROM chapters WHERE number = $1 AND novel_id = $2;",
            chapter_number, novel_id
        )
        if not chapter:
            logger.error(f"Chapter {chapter_number} not found in DB.")
            return

        # Build chunk-marked text + provenance id set (Invariant 8).
        marked_text, valid_chunk_ids, all_chunk_ids = await _load_chapter_chunks(novel_id, chapter_number, conn)
        if not all_chunk_ids:
            logger.warning(
                f"Chapter {chapter_number} has no chunks; run `chunk` before `extract` for provenance. "
                f"Proceeding with raw text and empty provenance."
            )
            extraction_body = chapter["content"]
        else:
            extraction_body = marked_text

        # 1. Compile forward context
        prev_summary = await get_running_summary(novel_id, chapter_number, conn)
        roster = await get_known_entities_roster(novel_id, chapter_number, conn)

        # 2. Invoke Flash for structured JSON extraction.
        # The roster leads the user message: it is append-only across chapters, so
        # leading with it lets the provider cache the system+roster prefix, while the
        # volatile running summary and chapter text follow.
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": EXTRACTION_USER.format(
                    roster=roster,
                    running_summary=prev_summary,
                    chapter_number=chapter_number,
                    chapter_title=chapter["title"],
                    chapter_text=extraction_body
                )
            }
        ]

        logger.info(f"Calling Flash extraction model for Chapter {chapter_number}...")
        data = await _call_and_parse(messages, f"Chapter {chapter_number} extraction")
        if not any(data[k] for k in EXTRACTION_KEYS):
            logger.warning(
                f"Chapter {chapter_number}: extraction returned no items of any kind — "
                f"possible silent miss (check that the chapter has text/chunks)."
            )

        # 2b. Optional verification pass: re-read the chapter against the first pass and
        # fold in anything it missed (esp. identity reveals/relationships). Best-effort —
        # a failure here never blocks ingestion; we proceed with the first-pass result.
        if settings.EXTRACTION_VERIFY:
            verify_messages = [
                {"role": "system", "content": EXTRACTION_VERIFY_SYSTEM},
                {
                    "role": "user",
                    "content": EXTRACTION_VERIFY_USER.format(
                        chapter_number=chapter_number,
                        chapter_title=chapter["title"],
                        chapter_text=extraction_body,
                        first_pass_json=json.dumps(data, ensure_ascii=False),
                    )
                },
            ]
            try:
                vdata = await _call_and_parse(verify_messages, f"Chapter {chapter_number} verification")
                added = 0
                for key in EXTRACTION_KEYS:
                    if vdata[key]:
                        data[key].extend(vdata[key])
                        added += len(vdata[key])
                if added:
                    logger.info(f"Verification pass added {added} missed item(s) for Chapter {chapter_number}.")
            except Exception as ve:
                logger.warning(
                    f"Verification pass failed for Chapter {chapter_number}; "
                    f"proceeding with first-pass extraction: {ve}"
                )

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
                    context_idx = chapter["content"].lower().find(surface.lower())
                    if context_idx != -1:
                        start = max(0, context_idx - 100)
                        end = min(len(chapter["content"]), context_idx + len(surface) + 100)
                        context_snippet = chapter["content"][start:end]

                entity_id = await resolve_entity(
                    novel_id=novel_id,
                    mention=ref or surface,
                    entity_type=etype,
                    chapter=chapter_number,
                    context=context_snippet,
                    conn=conn,
                    description=mdesc,
                )
                if ref:
                    local_ref_to_id[ref] = entity_id

                # Record the chapter-local description so the roster/UI can show the
                # freshest spoiler-safe blurb (not just the frozen first-seen one).
                if mdesc and mdesc.strip():
                    await conn.execute(
                        """
                        INSERT INTO entity_descriptions (novel_id, entity_id, chapter, description)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (entity_id, chapter) DO UPDATE SET description = EXCLUDED.description;
                        """,
                        novel_id, entity_id, chapter_number, mdesc.strip()
                    )

            async def get_entity_id(ref_name: str, fallback_type: str = "concept") -> int:
                if ref_name in local_ref_to_id:
                    return local_ref_to_id[ref_name]
                logger.info(f"Ref '{ref_name}' was not explicitly mentioned. Resolving dynamically...")
                entity_id = await resolve_entity(novel_id, ref_name, fallback_type, chapter_number, ref_name, conn)
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
                    INSERT INTO entity_facts (novel_id, entity_id, chapter, fact_type, content, source_chunk_ids)
                    VALUES ($1, $2, $3, $4, $5, $6);
                    """,
                    novel_id, fid, chapter_number, fact.get("fact_type"), fact.get("content"), src_ids
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
                    INSERT INTO relationships (novel_id, source_id, target_id, chapter, relation_type, directed, content, source_chunk_ids)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
                    """,
                    novel_id, src_id, tgt_id, chapter_number, rel.get("relation_type"),
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
                    INSERT INTO events (novel_id, chapter, description, participants, location_id, significance, source_chunk_ids)
                    VALUES ($1, $2, $3, $4, $5, $6, $7);
                    """,
                    novel_id, chapter_number, ev.get("description"), participants, loc_id,
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
                    INSERT INTO identity_links (novel_id, entity_a, entity_b, revealed_at_chapter, note)
                    VALUES ($1, $2, $3, $4, $5);
                    """,
                    novel_id, persona_id, true_id, chapter_number, reveal.get("note")
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
                    INSERT INTO entity_aliases (novel_id, entity_id, alias, revealed_at_chapter)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (entity_id, alias) DO UPDATE
                    SET revealed_at_chapter = LEAST(entity_aliases.revealed_at_chapter, EXCLUDED.revealed_at_chapter);
                    """,
                    novel_id, ent_id, alias_name, reveal_ch
                )

            # 9. Update running summary using Flash
            summary_messages = [
                {"role": "system", "content": SUMMARY_SYSTEM},
                {
                    "role": "user",
                    "content": SUMMARY_USER.format(
                        prev_summary=prev_summary,
                        title=chapter["title"],
                        # Feed (effectively) the whole chapter so end-of-chapter
                        # developments still reach the forward-carried summary. The
                        # cap only guards against pathologically huge chapters.
                        text=chapter["content"][:settings.SUMMARY_INPUT_MAX_CHARS]
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
                INSERT INTO extraction_state (novel_id, chapter, running_summary, processed_at)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (novel_id, chapter) DO UPDATE
                SET running_summary = EXCLUDED.running_summary, processed_at = now();
                """,
                novel_id, chapter_number, new_summary
            )

        logger.info(f"--- Chapter {chapter_number} Extraction Complete ---")


async def extract_all_chapters(
    novel_id: int,
    force: bool = False,
    from_chapter: float | None = None,
    to_chapter: float | None = None,
):
    """Processes chapters in strict ascending order (Invariant 2), optionally limited
    to a [from_chapter, to_chapter] range so the prompt can be iterated on the first
    ~50 chapters before committing to the full paid run."""
    pool = await get_db_pool()
    conditions = ["novel_id = $1"]
    args: list = [novel_id]
    if from_chapter is not None:
        args.append(from_chapter)
        conditions.append(f"number >= ${len(args)}")
    if to_chapter is not None:
        args.append(to_chapter)
        conditions.append(f"number <= ${len(args)}")
    where = " WHERE " + " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT number FROM chapters{where} ORDER BY number ASC;", *args)

    for row in rows:
        await extract_knowledge_for_chapter(novel_id, float(row["number"]), force=force)


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv

    async def main():
        novel_id = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1
        await extract_all_chapters(novel_id, force=force)
        await close_db_pool()

    asyncio.run(main())
