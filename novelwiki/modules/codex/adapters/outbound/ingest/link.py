import json
import logging
import asyncpg
from dataclasses import dataclass
from novelwiki.platform.config import settings
from novelwiki.modules.codex.adapters.outbound.cache import clear_caches
from novelwiki.modules.codex.domain.prompts import DISAMBIGUATION_SYSTEM, DISAMBIGUATION_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntityResolutionProposal:
    existing_id: int | None
    candidates: tuple[dict, ...] = ()

    @property
    def needs_disambiguation(self) -> bool:
        return self.existing_id is None and bool(self.candidates)


async def find_resolution_candidates(
    novel_id: int,
    mention: str,
    entity_type: str,
    chapter: float,
    context: str,
    conn: asyncpg.Connection,
    description: str | None = None,
    *,
    runtime,
) -> EntityResolutionProposal:
    """Deterministic exact/fuzzy/semantic stages used before AGY gray-case batching.

    This function never mutates the database and never invokes a generative model.
    """
    name = (mention or "").strip()
    if not name:
        raise ValueError("Mention name cannot be empty.")
    row = await conn.fetchrow(
        """
        SELECT e.id FROM entities e
        LEFT JOIN entity_aliases a ON e.id=a.entity_id AND a.revealed_at_chapter <= $2
        WHERE (lower(e.canonical_name)=lower($1) OR lower(a.alias)=lower($1))
          AND e.first_seen_chapter <= $2 AND e.novel_id=$3
          AND (e.type=$4 OR (e.type IN ('faction','organization') AND $4 IN ('faction','organization')))
        ORDER BY e.id LIMIT 1;
        """,
        name, chapter, novel_id, entity_type,
    )
    if row:
        return EntityResolutionProposal(int(row["id"]))
    rows = await conn.fetch(
        """
        SELECT e.id, e.canonical_name,
               GREATEST(similarity(e.canonical_name,$1), COALESCE(MAX(similarity(a.alias,$1)),0)) AS sim
        FROM entities e
        LEFT JOIN entity_aliases a ON e.id=a.entity_id AND a.revealed_at_chapter <= $2
        WHERE e.first_seen_chapter <= $2 AND e.novel_id=$4
          AND (e.type=$5 OR (e.type IN ('faction','organization') AND $5 IN ('faction','organization')))
        GROUP BY e.id, e.canonical_name
        HAVING GREATEST(similarity(e.canonical_name,$1), COALESCE(MAX(similarity(a.alias,$1)),0)) > $3
        ORDER BY sim DESC LIMIT 5;
        """,
        name, chapter, settings.FUZZY_MATCH_THRESHOLD, novel_id, entity_type,
    )
    candidates = tuple({"id": int(r["id"]), "canonical_name": r["canonical_name"],
                        "sim": float(r["sim"])} for r in rows)
    if len(candidates) == 1 and candidates[0]["sim"] >= settings.FUZZY_AUTO_ACCEPT:
        return EntityResolutionProposal(candidates[0]["id"])

    desc = (description or "").strip()
    embedding = await runtime.ai.get_embedding(f"{name}: {desc}" if desc else name)
    if embedding:
        vector = "[" + ",".join(map(str, embedding)) + "]"
        row = await conn.fetchrow(
            """
            SELECT id, 1-(name_embedding <=> $1::vector) AS sim FROM entities
            WHERE first_seen_chapter <= $2 AND novel_id=$3 AND name_embedding IS NOT NULL
              AND (type=$4 OR (type IN ('faction','organization') AND $4 IN ('faction','organization')))
            ORDER BY name_embedding <=> $1::vector LIMIT 1;
            """,
            vector, chapter, novel_id, entity_type,
        )
        if row and row["sim"] is not None and float(row["sim"]) > settings.SEMANTIC_MATCH_THRESHOLD:
            return EntityResolutionProposal(int(row["id"]))
    return EntityResolutionProposal(None, candidates)


async def create_entity(
    novel_id: int,
    mention: str,
    entity_type: str,
    chapter: float,
    conn: asyncpg.Connection,
    description: str | None = None,
    *,
    runtime,
) -> int:
    name = mention.strip()
    desc = (description or "").strip() or None
    embedding = await runtime.ai.get_embedding(f"{name}: {desc}" if desc else name)
    vector = "[" + ",".join(map(str, embedding)) + "]" if embedding else None
    entity_id = await conn.fetchval(
        """
        INSERT INTO entities (novel_id,canonical_name,type,description,name_embedding,first_seen_chapter)
        VALUES ($1,$2,$3,$4,$5::vector,$6) RETURNING id;
        """,
        novel_id, name, entity_type or "concept", desc, vector, chapter,
    )
    await conn.execute(
        """
        INSERT INTO entity_aliases (novel_id,entity_id,alias,revealed_at_chapter)
        VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING;
        """,
        novel_id, entity_id, name, chapter,
    )
    return int(entity_id)

async def resolve_entity(
    novel_id: int,
    mention: str,
    entity_type: str,
    chapter: float,
    context: str,
    conn: asyncpg.Connection,
    description: str | None = None,
    *,
    runtime,
) -> int:
    """
    Resolves a surface mention back to a canonical entities.id.
    Pre-filters candidates to avoid leaks (only visible at first_seen_chapter <= chapter).
    Steps:
      1. Exact name or alias match
      2. Trigram fuzzy match (with Flash LLM disambiguation if > 1 match)
      3. Semantic vector similarity fallback
      4. If still unresolved, creates a new entity.

    `description` (optional) is a short blurb derived from the chapter where the
    entity is first seen. It is stored ONLY on creation (never overwritten later)
    so it stays spoiler-safe, and is folded into the name_embedding for linking.
    """
    name_clean = mention.strip()
    if not name_clean:
        raise ValueError("Mention name cannot be empty.")

    desc_clean = (description or "").strip() or None
    embed_text = f"{name_clean}: {desc_clean}" if desc_clean else name_clean
        
    # ── Step 1: Exact Match ──
    # Check if matches canonical name or alias revealed on or before the current chapter
    row = await conn.fetchrow(
        """
        SELECT e.id FROM entities e
        LEFT JOIN entity_aliases a ON e.id = a.entity_id AND a.revealed_at_chapter <= $2
        WHERE (LOWER(e.canonical_name) = LOWER($1) OR LOWER(a.alias) = LOWER($1))
          AND e.first_seen_chapter <= $2 AND e.novel_id = $3
          AND (e.type=$4 OR (e.type IN ('faction','organization') AND $4 IN ('faction','organization')))
        ORDER BY e.id LIMIT 1;
        """,
        name_clean, chapter, novel_id, entity_type
    )
    if row:
        return int(row["id"])

    # ── Step 2: Fuzzy Match via pg_trgm ──
    # Fetch top candidates above the configured similarity floor.
    rows = await conn.fetch(
        """
        SELECT e.id, e.canonical_name,
               GREATEST(similarity(e.canonical_name,$1),COALESCE(MAX(similarity(a.alias,$1)),0)) AS sim
        FROM entities e
        LEFT JOIN entity_aliases a ON e.id = a.entity_id AND a.revealed_at_chapter <= $2
        WHERE (similarity(e.canonical_name, $1) > $3 OR similarity(a.alias, $1) > $3)
          AND e.first_seen_chapter <= $2 AND e.novel_id = $4
          AND (e.type=$5 OR (e.type IN ('faction','organization') AND $5 IN ('faction','organization')))
        GROUP BY e.id,e.canonical_name
        ORDER BY sim DESC
        LIMIT 5;
        """,
        name_clean, chapter, settings.FUZZY_MATCH_THRESHOLD, novel_id, entity_type
    )

    candidates = [dict(r) for r in rows]

    if len(candidates) == 1 and candidates[0]["sim"] >= settings.FUZZY_AUTO_ACCEPT:
        # High-confidence single candidate - resolve directly without an LLM call.
        logger.info(f"Fuzzy match resolved '{name_clean}' to candidate '{candidates[0]['canonical_name']}' (sim {candidates[0]['sim']:.2f})")
        return int(candidates[0]["id"])
    elif candidates:
        # Either multiple candidates, or a single candidate in the gray zone
        # ([FUZZY_MATCH_THRESHOLD, FUZZY_AUTO_ACCEPT)). Both are merge-risky, so let
        # Flash decide rather than auto-merging two similarly-named distinct entities.
        cand_list_str = "\n".join([f"- Candidate ID {c['id']}: {c['canonical_name']} (similarity score: {c['sim']:.2f})" for c in candidates])
        
        messages = [
            {"role": "system", "content": DISAMBIGUATION_SYSTEM},
            {
                "role": "user", 
                "content": DISAMBIGUATION_USER.format(
                    mention=name_clean,
                    entity_type=entity_type,
                    chapter=chapter,
                    context=context,
                    candidates_list=cand_list_str
                )
            }
        ]
        
        try:
            response = await runtime.ai.call_chat_completion(
                model=settings.MODEL_FLASH,
                messages=messages,
                temperature=0.0
            )
            # Remove any markdown code blocks if the model included them
            clean_resp = response.strip().replace("```json", "").replace("```", "").strip()
            import json_repair
            try:
                match_data = json.loads(clean_resp)
            except Exception as json_err:
                logger.warning(f"Standard JSON decoding failed for disambiguation: {json_err}. Attempting json-repair...")
                match_data = json_repair.loads(clean_resp)
            match_id = match_data.get("match_id")
            allowed_candidate_ids = {int(candidate["id"]) for candidate in candidates}
            if match_id != "NEW" and match_id is not None and int(match_id) in allowed_candidate_ids:
                logger.info(f"Disambiguator matched '{name_clean}' to ID {match_id}. Reason: {match_data.get('reason')}")
                return int(match_id)
        except Exception as e:
            logger.warning(f"Fuzzy LLM disambiguation failed: {e}. Falling back to semantic check.")

    # ── Step 3: Semantic Match / Vector Fallback ──
    emb = await runtime.ai.get_embedding(embed_text)
    if emb:
        emb_str = "[" + ",".join(map(str, emb)) + "]"
        row = await conn.fetchrow(
            """
            SELECT id, 1 - (name_embedding <=> $1::vector) AS sim
            FROM entities
            WHERE first_seen_chapter <= $2 AND novel_id = $3
              AND (type=$4 OR (type IN ('faction','organization') AND $4 IN ('faction','organization')))
            ORDER BY name_embedding <=> $1::vector
            LIMIT 1;
            """,
            emb_str, chapter, novel_id, entity_type
        )
        if row and row["sim"] > settings.SEMANTIC_MATCH_THRESHOLD:
            logger.info(f"Semantic match resolved '{name_clean}' to ID {row['id']} (similarity {row['sim']:.3f})")
            return int(row["id"])

    # ── Step 4: Create New Entity ──
    emb_str = "[" + ",".join(map(str, emb)) + "]" if emb else None

    entity_id = await conn.fetchval(
        """
        INSERT INTO entities (novel_id, canonical_name, type, description, name_embedding, first_seen_chapter)
        VALUES ($1, $2, $3, $4, $5::vector, $6)
        RETURNING id;
        """,
        novel_id, name_clean, entity_type, desc_clean, emb_str, chapter
    )

    # Insert default self-alias
    await conn.execute(
        """
        INSERT INTO entity_aliases (novel_id, entity_id, alias, revealed_at_chapter)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT DO NOTHING;
        """,
        novel_id, entity_id, name_clean, chapter,
    )
    
    logger.info(f"Unresolved mention. Created new Entity '{name_clean}' (ID: {entity_id}) at Chapter {chapter}.")
    return entity_id

async def merge_entities(novel_id: int, keep_id: int, drop_id: int, conn: asyncpg.Connection):
    """
    Merges duplicate entity IDs (drop_id into keep_id) cleanly,
    updating facts, relations, timelines, events, and aliases.
    """
    logger.info(f"Merging entity ID {drop_id} into keep ID {keep_id}...")

    if keep_id == drop_id:
        raise ValueError("keep and drop entity ids must differ")
    async with conn.transaction():
        await conn.execute(
            "SELECT pg_advisory_xact_lock($1::bigint);",
            7_200_000_000_000_000 + int(novel_id),
        )
        rows = await conn.fetch(
            "SELECT id FROM entities WHERE novel_id=$1 AND id=ANY($2::bigint[]) FOR UPDATE;",
            novel_id, [keep_id, drop_id],
        )
        if {int(row["id"]) for row in rows} != {keep_id, drop_id}:
            raise ValueError("both entities must belong to the supplied novel")
        # 1. Update facts
        await conn.execute(
            "UPDATE entity_facts SET entity_id = $1 WHERE entity_id = $2;", 
            keep_id, drop_id
        )
        
        # 2. Update relationships
        await conn.execute(
            "UPDATE relationships SET source_id = $1 WHERE source_id = $2;", 
            keep_id, drop_id
        )
        await conn.execute(
            "UPDATE relationships SET target_id = $1 WHERE target_id = $2;", 
            keep_id, drop_id
        )
        
        # 3. Update events participants (participants is a BIGINT array)
        await conn.execute(
            "UPDATE events SET participants=ARRAY(SELECT DISTINCT value FROM unnest(array_replace(participants,$2,$1)) value ORDER BY value) WHERE $2=ANY(participants);",
            keep_id, drop_id
        )
        
        # 4. Update events location
        await conn.execute(
            "UPDATE events SET location_id = $1 WHERE location_id = $2;", 
            keep_id, drop_id
        )

        # 4b. Move bounded-memory temporal references. Activity has a composite
        # key, so aggregate collisions before deleting the dropped rows.
        activity_rows = await conn.fetch(
            """
            SELECT novel_id,chapter,mention_count,claim_count,event_count,salience,
                   source_chunk_ids,pipeline_version
            FROM entity_activity WHERE entity_id=$1;
            """,
            drop_id,
        )
        for row in activity_rows:
            await conn.execute(
                """
                INSERT INTO entity_activity
                  (novel_id,entity_id,chapter,mention_count,claim_count,event_count,salience,
                   source_chunk_ids,pipeline_version)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (novel_id,entity_id,chapter,pipeline_version) DO UPDATE SET
                  mention_count=entity_activity.mention_count+EXCLUDED.mention_count,
                  claim_count=entity_activity.claim_count+EXCLUDED.claim_count,
                  event_count=entity_activity.event_count+EXCLUDED.event_count,
                  salience=entity_activity.salience+EXCLUDED.salience,
                  source_chunk_ids=ARRAY(
                    SELECT DISTINCT value FROM unnest(
                      entity_activity.source_chunk_ids || EXCLUDED.source_chunk_ids
                    ) value ORDER BY value
                  );
                """,
                row["novel_id"], keep_id, row["chapter"], row["mention_count"],
                row["claim_count"], row["event_count"], row["salience"],
                row["source_chunk_ids"], row["pipeline_version"],
            )
        await conn.execute("DELETE FROM entity_activity WHERE entity_id=$1;", drop_id)
        await conn.execute(
            "UPDATE entity_state_transitions SET entity_id=$1 WHERE entity_id=$2;",
            keep_id, drop_id,
        )
        await conn.execute(
            "UPDATE entity_state_transitions SET perspective_entity_id=$1 WHERE perspective_entity_id=$2;",
            keep_id, drop_id,
        )
        await conn.execute(
            "UPDATE relationship_state_transitions SET source_id=$1 WHERE source_id=$2;",
            keep_id, drop_id,
        )
        await conn.execute(
            "UPDATE relationship_state_transitions SET target_id=$1 WHERE target_id=$2;",
            keep_id, drop_id,
        )
        await conn.execute(
            "UPDATE plot_thread_updates SET participants=ARRAY(SELECT DISTINCT value FROM "
            "unnest(array_replace(participants,$2,$1)) value ORDER BY value) "
            "WHERE $2=ANY(participants);",
            keep_id, drop_id,
        )
        
        # 5. Union entity aliases
        aliases = await conn.fetch(
            "SELECT alias, revealed_at_chapter FROM entity_aliases WHERE entity_id = $1;", 
            drop_id
        )
        for row in aliases:
            await conn.execute(
                """
                INSERT INTO entity_aliases (novel_id,entity_id,alias,revealed_at_chapter)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT (entity_id, alias) DO UPDATE
                SET revealed_at_chapter = LEAST(entity_aliases.revealed_at_chapter, EXCLUDED.revealed_at_chapter);
                """,
                novel_id, keep_id, row["alias"], row["revealed_at_chapter"]
            )
            
        # 5b. Move per-chapter descriptions (keep the surviving entity's on conflict)
        await conn.execute(
            """
            INSERT INTO entity_descriptions (novel_id,entity_id,chapter,description)
            SELECT $1,$2,chapter,description FROM entity_descriptions WHERE entity_id=$3
            ON CONFLICT (entity_id, chapter) DO NOTHING;
            """,
            novel_id, keep_id, drop_id
        )

        # 6. Fold identity links, remove self-links, then delete old aliases.
        await conn.execute("UPDATE identity_links SET entity_a=$1 WHERE entity_a=$2;", keep_id, drop_id)
        await conn.execute("UPDATE identity_links SET entity_b=$1 WHERE entity_b=$2;", keep_id, drop_id)
        await conn.execute("DELETE FROM identity_links WHERE entity_a=entity_b;")
        await conn.execute("DELETE FROM entity_aliases WHERE entity_id = $1;", drop_id)
        
        # 7. Delete old entity
        await conn.execute("DELETE FROM entities WHERE id = $1;", drop_id)
        
        # 8. Invalidate affected caches
        await clear_caches(conn, novel_id=novel_id, entity_id=keep_id)
        await clear_caches(conn, novel_id=novel_id, entity_id=drop_id)
        
    logger.info(f"Entity ID {drop_id} merged into ID {keep_id} successfully.")
