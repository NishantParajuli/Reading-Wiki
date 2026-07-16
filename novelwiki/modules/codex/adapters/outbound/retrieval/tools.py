import json
import logging
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool
from novelwiki.modules.codex.adapters.outbound.context import (
    current_entity_state,
    current_relationship_state,
)
from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import get_bm25_manager
from novelwiki.modules.codex.adapters.outbound.retrieval.dense import dense_search
from novelwiki.modules.codex.adapters.outbound.retrieval.fuse import reciprocal_rank_fusion
from novelwiki.modules.codex.adapters.outbound.retrieval.rerank import rerank_hits

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Passage Retrieval Tools ───────────────────────────────────────────────

async def hybrid_search(
    novel_id: int, query: str, chapter_ceiling: float, k: int = 50, *, runtime
) -> list[dict]:
    """
    Executes hybrid search (BM25 + pgvector dense) with reciprocal rank fusion,
    scoped to a single novel. Enforces chapter_ceiling on both retrievers before fusion.
    """
    logger.info(f"Hybrid search (novel {novel_id}): '{query}' at ceiling {chapter_ceiling}")

    # 1. Sparse BM25 Search (per-novel index; pre-filters <= ceiling internally).
    # asearch() offloads the blocking tokenize/retrieve off the event loop.
    manager = get_bm25_manager(novel_id)
    await manager.ensure_loaded()
    sparse_hits = await manager.asearch(query, chapter_ceiling, k=k)

    # 2. Dense Vector Search (pre-filters <= ceiling internally)
    dense_hits = await dense_search(
        novel_id, query, chapter_ceiling, k=k, runtime=runtime
    )

    # 3. Reciprocal Rank Fusion
    fused_hits = reciprocal_rank_fusion(sparse_hits, dense_hits)

    # Limit to top k
    return fused_hits[:k]

async def rerank(query: str, hits: list[dict], top_n: int = 8, *, runtime) -> list[dict]:
    """Reranks candidate hits using Cohere Rerank via OpenRouter."""
    return await rerank_hits(query, hits, top_n=top_n, runtime=runtime)

async def get_chunk(novel_id: int, chunk_id: int, chapter_ceiling: float) -> dict | None:
    """Verbatim chunk drill-down. Strictly returns None if chunk is beyond the ceiling."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, chapter, chunk_index, text, token_count
            FROM chunks
            WHERE id = $1 AND chapter <= $2 AND novel_id = $3;
            """,
            chunk_id, chapter_ceiling, novel_id
        )
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "chapter": float(row["chapter"]),
            "chunk_index": int(row["chunk_index"]),
            "text": row["text"],
            "token_count": int(row["token_count"])
        }

# ── Phase 4 Structured Tools ──────────────────────────────────────────────

async def get_connected_personas(novel_id: int, entity_id: int, chapter_ceiling: float, conn) -> list[int]:
    """
    Uses recursive CTE to retrieve all interconnected persona entity IDs
    revealed up to and including the current chapter_ceiling, within this novel.
    Traverses the identity_links undirected graph safely and without duplicate recursion terms.
    """
    rows = await conn.fetch(
        """
        WITH RECURSIVE connected(entity_id) AS (
            SELECT e.id AS entity_id
            FROM entities e
            WHERE e.id = $1 AND e.novel_id = $3 AND e.first_seen_chapter <= $2
            UNION
            SELECT other.id AS entity_id
            FROM identity_links l
            JOIN connected c ON (l.entity_a = c.entity_id OR l.entity_b = c.entity_id)
            JOIN entities other ON other.id =
                CASE
                    WHEN l.entity_a = c.entity_id THEN l.entity_b
                    ELSE l.entity_a
                END
            WHERE l.revealed_at_chapter <= $2 AND l.novel_id = $3
              AND other.novel_id = $3 AND other.first_seen_chapter <= $2
        )
        SELECT entity_id FROM connected;
        """,
        entity_id, chapter_ceiling, novel_id
    )
    return [int(r["entity_id"]) for r in rows]


async def resolve_entity(novel_id: int, name: str, chapter_ceiling: float) -> list[dict]:
    """
    Resolves a name to matching entities visible below chapter_ceiling in this novel.
    Uses exact alias/name match, fuzzy trgm, or semantic fallback.
    Returns: list of {"id", "canonical_name", "type", "first_seen_chapter", "linked_ids"}
    """
    pool = await get_db_pool()
    name_clean = name.strip()
    if not name_clean:
        return []

    async with pool.acquire() as conn:
        # 1. Exact alias/name match below ceiling
        rows = await conn.fetch(
            """
            SELECT DISTINCT e.id, e.canonical_name, e.type, e.first_seen_chapter
            FROM entities e
            LEFT JOIN entity_aliases a ON e.id = a.entity_id AND a.revealed_at_chapter <= $2
            WHERE (LOWER(e.canonical_name) = LOWER($1) OR LOWER(a.alias) = LOWER($1))
              AND e.first_seen_chapter <= $2 AND e.novel_id = $3
            ORDER BY e.id LIMIT $4;
            """,
            name_clean, chapter_ceiling, novel_id, settings.CODEX_READ_MAX_ENTITIES,
        )

        # 2. Fuzzy match fallback
        if not rows:
            rows = await conn.fetch(
                """
                SELECT DISTINCT e.id, e.canonical_name, e.type, e.first_seen_chapter, similarity(e.canonical_name, $1) AS score
                FROM entities e
                LEFT JOIN entity_aliases a ON e.id = a.entity_id AND a.revealed_at_chapter <= $2
                WHERE (similarity(e.canonical_name, $1) > 0.3 OR similarity(a.alias, $1) > 0.3)
                  AND e.first_seen_chapter <= $2 AND e.novel_id = $3
                ORDER BY score DESC
                LIMIT 5;
                """,
                name_clean, chapter_ceiling, novel_id
            )

        results = []
        for r in rows:
            linked_ids = await get_connected_personas(novel_id, r["id"], chapter_ceiling, conn)
            results.append({
                "id": int(r["id"]),
                "canonical_name": r["canonical_name"],
                "type": r["type"],
                "first_seen_chapter": float(r["first_seen_chapter"]),
                "linked_ids": linked_ids
            })
        return results

async def get_entity_profile(novel_id: int, entity_id: int, chapter_ceiling: float) -> dict | None:
    """
    Fetches full profile (facts, folded identities) for an entity below ceiling.
    Folds facts and aliases of connected personas.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        # 1. Get current base entity metadata, with the freshest spoiler-safe
        # description (latest observed at/below the ceiling, else first-seen blurb).
        entity = await conn.fetchrow(
            """
            SELECT e.id, e.canonical_name, e.type,
                   COALESCE(d.description, e.description) AS description,
                   e.first_seen_chapter
            FROM entities e
            LEFT JOIN LATERAL (
                SELECT description FROM entity_descriptions ed
                WHERE ed.entity_id = e.id AND ed.chapter <= $2
                ORDER BY ed.chapter DESC LIMIT 1
            ) d ON TRUE
            WHERE e.id = $1 AND e.first_seen_chapter <= $2 AND e.novel_id = $3;
            """,
            entity_id, chapter_ceiling, novel_id
        )
        if not entity:
            return None

        # 2. Get connected personas at this ceiling
        linked_ids = await get_connected_personas(novel_id, entity_id, chapter_ceiling, conn)

        # 3. Retrieve facts for any connected personas <= ceiling
        facts_rows = await conn.fetch(
            """
            SELECT id, chapter, fact_type, content, data
            FROM entity_facts
            WHERE entity_id = ANY($1) AND chapter <= $2 AND novel_id = $3
            ORDER BY chapter DESC, id DESC
            LIMIT $4;
            """,
            linked_ids, chapter_ceiling, novel_id, settings.CODEX_READ_MAX_FACTS,
        )

        # 4. Retrieve aliases <= ceiling
        aliases_rows = await conn.fetch(
            """
            SELECT alias, revealed_at_chapter
            FROM entity_aliases
            WHERE entity_id = ANY($1) AND revealed_at_chapter <= $2 AND novel_id = $3
            ORDER BY revealed_at_chapter DESC,alias LIMIT 200;
            """,
            linked_ids, chapter_ceiling, novel_id
        )

        facts = [
            {
                "id": int(r["id"]),
                "chapter": float(r["chapter"]),
                "fact_type": r["fact_type"],
                "content": r["content"],
                "data": r["data"]
            }
            for r in reversed(facts_rows)
        ]

        aliases = [r["alias"] for r in aliases_rows]

        state_by_entity = await current_entity_state(
            conn, novel_id, linked_ids, chapter_ceiling
        )
        relationship_state_rows = await current_relationship_state(
            conn, novel_id, linked_ids, chapter_ceiling,
        )
        thread_rows = await conn.fetch(
            """
            SELECT t.id,t.stable_title,u.id update_id,u.operation,u.summary,u.chapter,
                   u.source_chunk_ids
            FROM plot_threads t
            JOIN LATERAL (
              SELECT operation,summary,participants,chapter,id,source_chunk_ids
              FROM plot_thread_updates
              WHERE thread_id=t.id AND novel_id=$1 AND chapter <= $2
                AND pipeline_version=$3
              ORDER BY chapter DESC,id DESC LIMIT 1
            ) u ON TRUE
            WHERE t.novel_id=$1 AND t.pipeline_version=$3
              AND u.participants && $4::bigint[]
              AND u.operation NOT IN ('resolve','mark_dormant')
            ORDER BY u.chapter DESC LIMIT $5;
            """,
            novel_id, chapter_ceiling, settings.CODEX_PIPELINE_VERSION, linked_ids,
            settings.CODEX_CONTEXT_MAX_THREADS,
        )
        return {
            "id": int(entity["id"]),
            "canonical_name": entity["canonical_name"],
            "type": entity["type"],
            "description": entity["description"],
            "first_seen_chapter": float(entity["first_seen_chapter"]),
            "aliases": sorted(set(aliases), key=str.casefold),
            "facts": facts,
            "linked_personas": linked_ids,
            "current_state": state_by_entity,
            "relationship_state": relationship_state_rows,
            "open_threads": [dict(row) for row in thread_rows],
            "limits": {"facts": settings.CODEX_READ_MAX_FACTS},
        }

async def get_relationships(
    novel_id: int,
    entity_id: int,
    chapter_ceiling: float,
    other_id: int | None = None
) -> list[dict]:
    """
    Fetches relationships involving entity_id (or its connected personas) below ceiling.
    If other_id is specified, returns only relationship developments between them.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        linked_ids = await get_connected_personas(novel_id, entity_id, chapter_ceiling, conn)
        if not linked_ids:
            return []

        if other_id:
            other_linked_ids = await get_connected_personas(novel_id, other_id, chapter_ceiling, conn)
            if not other_linked_ids:
                return []
            rows = await conn.fetch(
                """
                SELECT r.id, r.source_id, r.target_id, r.chapter, r.relation_type, r.directed, r.content, r.data,
                       e1.canonical_name AS source_name, e1.type AS source_type,
                       e2.canonical_name AS target_name, e2.type AS target_type
                FROM relationships r
                JOIN entities e1 ON r.source_id = e1.id
                JOIN entities e2 ON r.target_id = e2.id
                WHERE ((r.source_id = ANY($1) AND r.target_id = ANY($2)) OR
                       (r.source_id = ANY($2) AND r.target_id = ANY($1)))
                  AND r.chapter <= $3 AND r.novel_id = $4
                  AND e1.novel_id = $4 AND e2.novel_id = $4
                  AND e1.first_seen_chapter <= $3 AND e2.first_seen_chapter <= $3
                ORDER BY r.chapter DESC,r.id DESC LIMIT $5;
                """,
                linked_ids, other_linked_ids, chapter_ceiling, novel_id,
                settings.CODEX_READ_MAX_RELATIONSHIPS,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT r.id, r.source_id, r.target_id, r.chapter, r.relation_type, r.directed, r.content, r.data,
                       e1.canonical_name AS source_name, e1.type AS source_type,
                       e2.canonical_name AS target_name, e2.type AS target_type
                FROM relationships r
                JOIN entities e1 ON r.source_id = e1.id
                JOIN entities e2 ON r.target_id = e2.id
                WHERE (r.source_id = ANY($1) OR r.target_id = ANY($1)) AND r.chapter <= $2 AND r.novel_id = $3
                  AND e1.novel_id = $3 AND e2.novel_id = $3
                  AND e1.first_seen_chapter <= $2 AND e2.first_seen_chapter <= $2
                ORDER BY r.chapter DESC,r.id DESC LIMIT $4;
                """,
                linked_ids, chapter_ceiling, novel_id,
                settings.CODEX_READ_MAX_RELATIONSHIPS,
            )

        return [
            {
                "id": int(r["id"]),
                "source_id": int(r["source_id"]),
                "source_name": r["source_name"],
                "source_type": r["source_type"],
                "target_id": int(r["target_id"]),
                "target_name": r["target_name"],
                "target_type": r["target_type"],
                "chapter": float(r["chapter"]),
                "relation_type": r["relation_type"],
                "directed": r["directed"],
                "content": r["content"],
                "data": r["data"]
            }
            for r in reversed(rows)
        ]


async def get_identity_links(novel_id: int, entity_id: int, chapter_ceiling: float) -> list[dict]:
    """
    Returns in-story identity reveals (persona == persona) visible at the ceiling.
    For the queried entity, each row is the OTHER persona it has been revealed to be
    the same being as — gated by revealed_at_chapter <= ceiling AND the other entity's
    first_seen_chapter <= ceiling. This is the spoiler-safe "the masked man is X" link;
    below the reveal chapter it returns nothing in either direction.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        linked_ids = await get_connected_personas(novel_id, entity_id, chapter_ceiling, conn)
        results = []
        for other_id in linked_ids:
            if other_id == entity_id:
                continue
            # The reveal chapter + note for the link that introduces this persona.
            link = await conn.fetchrow(
                """
                SELECT id, revealed_at_chapter, note
                FROM identity_links
                WHERE (entity_a = $1 OR entity_b = $1) AND revealed_at_chapter <= $2 AND novel_id = $3
                ORDER BY revealed_at_chapter ASC
                LIMIT 1;
                """,
                other_id, chapter_ceiling, novel_id
            )
            other = await conn.fetchrow(
                "SELECT canonical_name, type FROM entities WHERE id = $1 AND first_seen_chapter <= $2 AND novel_id = $3;",
                other_id, chapter_ceiling, novel_id
            )
            if not other:
                continue
            results.append({
                "id": int(link["id"]) if link else None,
                "other_id": int(other_id),
                "other_name": other["canonical_name"],
                "other_type": other["type"],
                "revealed_at_chapter": float(link["revealed_at_chapter"]) if link else float(chapter_ceiling),
                "note": link["note"] if link else None,
            })
        return results

async def get_timeline(novel_id: int, entity_id: int, chapter_ceiling: float) -> list[dict]:
    """
    Chronologically aggregates facts and events involving an entity (or its linked personas)
    at or below the chapter_ceiling.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        linked_ids = await get_connected_personas(novel_id, entity_id, chapter_ceiling, conn)
        if not linked_ids:
            return []

        # Fetch facts
        facts = await conn.fetch(
            """
            SELECT id, chapter, fact_type, content, 'fact' AS type
            FROM entity_facts
            WHERE entity_id = ANY($1) AND chapter <= $2 AND novel_id = $3
            ORDER BY chapter DESC,id DESC LIMIT $4;
            """,
            linked_ids, chapter_ceiling, novel_id, settings.CODEX_READ_MAX_TIMELINE_ITEMS,
        )

        # Fetch events
        events = await conn.fetch(
            """
            SELECT id, chapter, description, 'event' AS type
            FROM events
            WHERE (participants && $1 OR location_id = ANY($1)) AND chapter <= $2 AND novel_id = $3
            ORDER BY chapter DESC,id DESC LIMIT $4;
            """,
            linked_ids, chapter_ceiling, novel_id, settings.CODEX_READ_MAX_TIMELINE_ITEMS,
        )

        timeline = []
        for r in facts:
            timeline.append({
                "id": int(r["id"]),
                "chapter": float(r["chapter"]),
                "type": "fact",
                "label": f"Fact ({r['fact_type']})",
                "content": r["content"]
            })
        for r in events:
            timeline.append({
                "id": int(r["id"]),
                "chapter": float(r["chapter"]),
                "type": "event",
                "label": "Event",
                "content": r["description"]
            })

        # Sort chronologically, then by ID
        timeline.sort(key=lambda x: (x["chapter"], x["id"]))
        return timeline[-settings.CODEX_READ_MAX_TIMELINE_ITEMS:]

async def list_entities(
    novel_id: int,
    chapter_ceiling: float,
    entity_type: str | None = None,
    name_query: str | None = None
) -> list[dict]:
    """
    Lists all known entities first seen on or below chapter_ceiling in this novel,
    optionally filtering by type and checking matching aliases.
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        query = """
            SELECT e.id, e.canonical_name, e.type,
                   COALESCE(d.description, e.description) AS description,
                   e.first_seen_chapter
            FROM entities e
            LEFT JOIN LATERAL (
                SELECT description FROM entity_descriptions ed
                WHERE ed.entity_id = e.id AND ed.chapter <= $1
                ORDER BY ed.chapter DESC LIMIT 1
            ) d ON TRUE
            WHERE e.first_seen_chapter <= $1 AND e.novel_id = $2
        """
        args = [chapter_ceiling, novel_id]

        if entity_type:
            query += f" AND type = ${len(args)+1}"
            args.append(entity_type)

        if name_query:
            param_idx = len(args) + 1
            query += f"""
                AND (canonical_name ILIKE ${param_idx} OR id IN (
                    SELECT entity_id FROM entity_aliases
                    WHERE alias ILIKE ${param_idx} AND revealed_at_chapter <= $1 AND novel_id = $2
                ))
            """
            args.append(f"%{name_query}%")

        query += f" ORDER BY canonical_name ASC LIMIT ${len(args)+1};"
        args.append(settings.CODEX_READ_MAX_ENTITIES)
        rows = await conn.fetch(query, *args)

        return [
            {
                "id": int(r["id"]),
                "canonical_name": r["canonical_name"],
                "type": r["type"],
                "description": r["description"],
                "first_seen_chapter": float(r["first_seen_chapter"])
            }
            for r in rows
        ]
