import json
import logging
import asyncio
import asyncpg
import hashlib
import uuid
from collections.abc import Awaitable, Callable

from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool, close_db_pool
from novelwiki.modules.codex.adapters.outbound.cache import clear_caches
from novelwiki.modules.ai_execution.public import call_chat_completion
from novelwiki.modules.codex.adapters.outbound.ingest.link import create_entity, resolve_entity
from novelwiki.modules.codex.domain.prompts import (
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


def chapter_source_sha256(content: str | None) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


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


async def _clear_extraction_chapter(conn: asyncpg.Connection, novel_id: int, chapter: float) -> None:
    """Remove chapter-scoped material before a controlled force rebuild."""
    await conn.execute("DELETE FROM entity_facts WHERE novel_id=$1 AND chapter=$2;", novel_id, chapter)
    await conn.execute("DELETE FROM relationships WHERE novel_id=$1 AND chapter=$2;", novel_id, chapter)
    await conn.execute("DELETE FROM events WHERE novel_id=$1 AND chapter=$2;", novel_id, chapter)
    await conn.execute("DELETE FROM entity_descriptions WHERE novel_id=$1 AND chapter=$2;", novel_id, chapter)
    await conn.execute("DELETE FROM identity_links WHERE novel_id=$1 AND revealed_at_chapter=$2;", novel_id, chapter)
    await conn.execute(
        "DELETE FROM entity_aliases WHERE novel_id=$1 AND revealed_at_chapter=$2 AND revealed_at_chapter<>0;",
        novel_id, chapter,
    )
    # Later running summaries depend on this chapter. Explicitly remove stale
    # checkpoints; chronological rebuild recreates them as it advances.
    await conn.execute("DELETE FROM extraction_state WHERE novel_id=$1 AND chapter >= $2;", novel_id, chapter)


async def commit_extraction_proposal(
    novel_id: int,
    chapter_number: float,
    data: dict,
    running_summary: str,
    *,
    expected_source_hash: str,
    resolved_refs: dict[str, int | None],
    roster_refs: dict[str, int] | None = None,
    entity_resolver=None,
    run_id: uuid.UUID | None = None,
    model_label: str | None = None,
    force: bool = False,
) -> dict:
    """Transactionally commit a validated provider proposal.

    The provider has no DB/commit tool. ``resolved_refs`` comes from deterministic
    matching plus a separately validated gray-case decision batch; arbitrary IDs
    in model output are never accepted.
    """
    normalized = _coerce_extraction(data)
    if not running_summary or not running_summary.strip():
        raise ValueError("running summary must not be empty")
    roster_refs = dict(roster_refs or {})
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            from novelwiki.bootstrap.reading_migration import bind_reading_codex
            chapter = await bind_reading_codex(conn).locked_chapter_snapshot(
                novel_id, chapter_number
            )
            if not chapter or chapter_source_sha256(chapter["content"]) != expected_source_hash:
                raise RuntimeError("source_changed")
            existing = await conn.fetchrow(
                "SELECT run_id,source_sha256 FROM extraction_state "
                "WHERE novel_id=$1 AND chapter=$2 FOR UPDATE;", novel_id, chapter_number,
            )
            if existing and run_id is not None and existing["run_id"] == run_id \
                    and existing["source_sha256"] == expected_source_hash:
                return {"status": "done", "idempotent": True}
            if existing and not force:
                raise RuntimeError("chapter extraction was committed by another worker")
            if force:
                await _clear_extraction_chapter(conn, novel_id, chapter_number)
            await clear_caches(conn, novel_id=novel_id, chapter_number=chapter_number)
            _marked, valid_chunk_ids, all_chunk_ids = await _load_chapter_chunks(
                novel_id, chapter_number, conn,
            )
            local: dict[str, int] = dict(roster_refs)

            for mention in normalized["mentions"]:
                ref = str(mention.get("entity_ref") or "").strip()
                surface = str(mention.get("surface_form") or ref).strip()
                if not ref or not surface or ref in roster_refs:
                    continue
                if ref in resolved_refs:
                    entity = resolved_refs[ref]
                elif entity_resolver is not None:
                    position = (chapter["content"] or "").lower().find(surface.lower())
                    context = ((chapter["content"] or "")[max(0, position-100):position+len(surface)+100]
                               if position >= 0 else surface)
                    entity = await entity_resolver(
                        novel_id=novel_id, mention=ref or surface,
                        entity_type=mention.get("type") or "concept", chapter=chapter_number,
                        context=context, conn=conn, description=mention.get("description"),
                    )
                else:
                    raise ValueError(f"unresolved entity reference: {ref}")
                if entity is None:
                    entity = await create_entity(
                        novel_id, surface, mention.get("type") or "concept", chapter_number,
                        conn, description=mention.get("description"),
                    )
                local[ref] = int(entity)
                description = (mention.get("description") or "").strip()
                if description:
                    await conn.execute(
                        """
                        INSERT INTO entity_descriptions (novel_id,entity_id,chapter,description)
                        VALUES ($1,$2,$3,$4) ON CONFLICT (entity_id,chapter) DO UPDATE
                        SET description=EXCLUDED.description;
                        """,
                        novel_id, entity, chapter_number, description,
                    )

            async def ensure_entity_id(ref, fallback_type="concept") -> int:
                key = str(ref or "").strip()
                if key in local:
                    return local[key]
                if entity_resolver is None:
                    raise ValueError(f"proposal references unknown entity ref: {key}")
                entity = await entity_resolver(
                    novel_id=novel_id, mention=key, entity_type=fallback_type,
                    chapter=chapter_number, context=key, conn=conn,
                )
                local[key] = int(entity)
                return int(entity)

            for fact in normalized["facts"]:
                if not fact.get("entity_ref") or not fact.get("content"):
                    continue
                await conn.execute(
                    """
                    INSERT INTO entity_facts (novel_id,entity_id,chapter,fact_type,content,source_chunk_ids)
                    VALUES ($1,$2,$3,$4,$5,$6);
                    """,
                    novel_id, await ensure_entity_id(fact["entity_ref"]), chapter_number,
                    fact.get("fact_type"), fact["content"],
                    _clean_chunk_ids(fact.get("source_chunk_ids"), valid_chunk_ids, all_chunk_ids),
                )
            for rel in normalized["relationships"]:
                if not rel.get("source_ref") or not rel.get("target_ref"):
                    continue
                await conn.execute(
                    """
                    INSERT INTO relationships
                      (novel_id,source_id,target_id,chapter,relation_type,directed,content,source_chunk_ids)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8);
                    """,
                    novel_id, await ensure_entity_id(rel["source_ref"], "character"),
                    await ensure_entity_id(rel["target_ref"], "character"),
                    chapter_number, rel.get("relation_type"), bool(rel.get("directed", True)),
                    rel.get("content"),
                    _clean_chunk_ids(rel.get("source_chunk_ids"), valid_chunk_ids, all_chunk_ids),
                )
            for event in normalized["events"]:
                participants = [await ensure_entity_id(ref, "character") for ref in (event.get("participant_refs") or []) if ref]
                location = await ensure_entity_id(event["location_ref"], "location") if event.get("location_ref") else None
                await conn.execute(
                    """
                    INSERT INTO events
                      (novel_id,chapter,description,participants,location_id,significance,source_chunk_ids)
                    VALUES ($1,$2,$3,$4,$5,$6,$7);
                    """,
                    novel_id, chapter_number, event.get("description"), participants, location,
                    event.get("significance"),
                    _clean_chunk_ids(event.get("source_chunk_ids"), valid_chunk_ids, all_chunk_ids),
                )
            for reveal in normalized["identity_reveals"]:
                if not reveal.get("persona_ref") or not reveal.get("true_entity_ref"):
                    continue
                persona = await ensure_entity_id(reveal["persona_ref"], "character")
                true = await ensure_entity_id(reveal["true_entity_ref"], "character")
                if persona != true:
                    await conn.execute(
                        """
                        INSERT INTO identity_links (novel_id,entity_a,entity_b,revealed_at_chapter,note)
                        VALUES ($1,$2,$3,$4,$5);
                        """,
                        novel_id, persona, true, chapter_number, reveal.get("note"),
                    )
            for alias in normalized["new_aliases"]:
                if not alias.get("entity_ref") or not alias.get("alias"):
                    continue
                reveal_at = chapter_number if alias.get("is_reveal") else 0.0
                await conn.execute(
                    """
                    INSERT INTO entity_aliases (novel_id,entity_id,alias,revealed_at_chapter)
                    VALUES ($1,$2,$3,$4) ON CONFLICT (entity_id,alias) DO UPDATE
                    SET revealed_at_chapter=LEAST(entity_aliases.revealed_at_chapter,EXCLUDED.revealed_at_chapter);
                    """,
                    novel_id, await ensure_entity_id(alias["entity_ref"]), alias["alias"], reveal_at,
                )
            await conn.execute(
                """
                INSERT INTO extraction_state
                  (novel_id,chapter,running_summary,run_id,model_label,source_sha256,processed_at)
                VALUES ($1,$2,$3,$4,$5,$6,now())
                ON CONFLICT (novel_id,chapter) DO UPDATE SET
                  running_summary=EXCLUDED.running_summary, run_id=EXCLUDED.run_id,
                  model_label=EXCLUDED.model_label, source_sha256=EXCLUDED.source_sha256,
                  processed_at=now();
                """,
                novel_id, chapter_number, running_summary.strip(), run_id,
                model_label, expected_source_hash,
            )
    return {"status": "done", "idempotent": False}


async def extract_knowledge_for_chapter(
    novel_id: int,
    chapter_number: float,
    force: bool = False,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
):
    """
    Extracts structured knowledge from chapter_number in a forward-only transaction.
    """
    if cancel_check is not None:
        await cancel_check()
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
        from novelwiki.bootstrap.reading_migration import build_reading_codex_gateway
        chapter = await (await build_reading_codex_gateway()).chapter_snapshot(
            novel_id, chapter_number
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
        if cancel_check is not None:
            await cancel_check()
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
            if cancel_check is not None:
                await cancel_check()

        # 3. Build the forward summary proposal, then send both provider paths
        # through the same source-checked transactional commit adapter.
        summary_messages = [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {
                "role": "user",
                "content": SUMMARY_USER.format(
                    prev_summary=prev_summary,
                    title=chapter["title"],
                    text=chapter["content"][:settings.SUMMARY_INPUT_MAX_CHARS],
                ),
            },
        ]
        if cancel_check is not None:
            await cancel_check()
        logger.info(f"Generating updated running summary through Chapter {chapter_number}...")
        new_summary = await call_chat_completion(
            model=settings.MODEL_FLASH,
            messages=summary_messages,
            temperature=0.3,
        )
        if cancel_check is not None:
            await cancel_check()
        await commit_extraction_proposal(
            novel_id,
            chapter_number,
            data,
            new_summary,
            expected_source_hash=chapter_source_sha256(chapter["content"]),
            resolved_refs={},
            entity_resolver=resolve_entity,
            model_label=settings.MODEL_FLASH,
            force=force,
        )
        logger.info(f"--- Chapter {chapter_number} Extraction Complete ---")


async def extract_all_chapters(
    novel_id: int,
    force: bool = False,
    from_chapter: float | None = None,
    to_chapter: float | None = None,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
):
    """Processes chapters in strict ascending order (Invariant 2), optionally limited
    to a [from_chapter, to_chapter] range so the prompt can be iterated on the first
    ~50 chapters before committing to the full paid run."""
    from novelwiki.bootstrap.reading_migration import build_reading_codex_gateway
    numbers = await (await build_reading_codex_gateway()).chapter_numbers(
        novel_id, from_chapter, to_chapter
    )

    for number in numbers:
        if cancel_check is not None:
            await cancel_check()
        await extract_knowledge_for_chapter(
            novel_id, number, force=force, cancel_check=cancel_check,
        )


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv

    async def main():
        novel_id = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1
        await extract_all_chapters(novel_id, force=force)
        await close_db_pool()

    asyncio.run(main())
