import json
import logging
import asyncpg
from novelwiki.config.settings import settings
from novelwiki.db.queries import clear_caches
from novelwiki.agent.llm_client import call_chat_completion, get_embedding
from novelwiki.agent.prompts import DISAMBIGUATION_SYSTEM, DISAMBIGUATION_USER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def resolve_entity(
    mention: str,
    entity_type: str,
    chapter: float,
    context: str,
    conn: asyncpg.Connection,
    description: str | None = None,
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
          AND e.first_seen_chapter <= $2
        LIMIT 1;
        """,
        name_clean, chapter
    )
    if row:
        return int(row["id"])
        
    # ── Step 2: Fuzzy Match via pg_trgm ──
    # Fetch top candidates above 0.35 similarity threshold
    rows = await conn.fetch(
        """
        SELECT DISTINCT e.id, e.canonical_name, similarity(e.canonical_name, $1) AS sim
        FROM entities e
        LEFT JOIN entity_aliases a ON e.id = a.entity_id AND a.revealed_at_chapter <= $2
        WHERE (similarity(e.canonical_name, $1) > 0.35 OR similarity(a.alias, $1) > 0.35)
          AND e.first_seen_chapter <= $2
        ORDER BY sim DESC
        LIMIT 5;
        """,
        name_clean, chapter
    )
    
    candidates = [dict(r) for r in rows]
    
    if len(candidates) == 1:
        # Single candidate passes fuzzy - resolve directly
        logger.info(f"Fuzzy match resolved '{name_clean}' to candidate '{candidates[0]['canonical_name']}'")
        return int(candidates[0]["id"])
    elif len(candidates) > 1:
        # Multiple candidates found - use Flash to disambiguate
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
            response = await call_chat_completion(
                model=settings.MODEL_FLASH,
                messages=messages,
                temperature=0.0
            )
            # Remove any markdown code blocks if the model included them
            clean_resp = response.strip().replace("```json", "").replace("```", "").strip()
            match_data = json.loads(clean_resp)
            match_id = match_data.get("match_id")
            if match_id != "NEW" and match_id is not None:
                logger.info(f"Disambiguator matched '{name_clean}' to ID {match_id}. Reason: {match_data.get('reason')}")
                return int(match_id)
        except Exception as e:
            logger.warning(f"Fuzzy LLM disambiguation failed: {e}. Falling back to semantic check.")

    # ── Step 3: Semantic Match / Vector Fallback ──
    emb = await get_embedding(embed_text)
    if emb:
        emb_str = "[" + ",".join(map(str, emb)) + "]"
        row = await conn.fetchrow(
            """
            SELECT id, 1 - (name_embedding <=> $1::vector) AS sim
            FROM entities
            WHERE first_seen_chapter <= $2
            ORDER BY name_embedding <=> $1::vector
            LIMIT 1;
            """,
            emb_str, chapter
        )
        if row and row["sim"] > 0.85:
            logger.info(f"Semantic match resolved '{name_clean}' to ID {row['id']} (similarity {row['sim']:.3f})")
            return int(row["id"])

    # ── Step 4: Create New Entity ──
    emb_str = "[" + ",".join(map(str, emb)) + "]" if emb else None

    entity_id = await conn.fetchval(
        """
        INSERT INTO entities (canonical_name, type, description, name_embedding, first_seen_chapter)
        VALUES ($1, $2, $3, $4::vector, $5)
        RETURNING id;
        """,
        name_clean, entity_type, desc_clean, emb_str, chapter
    )
    
    # Insert default self-alias
    await conn.execute(
        """
        INSERT INTO entity_aliases (entity_id, alias, revealed_at_chapter)
        VALUES ($1, $2, 0.0)
        ON CONFLICT DO NOTHING;
        """,
        entity_id, name_clean
    )
    
    logger.info(f"Unresolved mention. Created new Entity '{name_clean}' (ID: {entity_id}) at Chapter {chapter}.")
    return entity_id

async def merge_entities(keep_id: int, drop_id: int, conn: asyncpg.Connection):
    """
    Merges duplicate entity IDs (drop_id into keep_id) cleanly,
    updating facts, relations, timelines, events, and aliases.
    """
    logger.info(f"Merging entity ID {drop_id} into keep ID {keep_id}...")
    
    async with conn.transaction():
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
            "UPDATE events SET participants = array_replace(participants, $2, $1) WHERE $2 = ANY(participants);", 
            keep_id, drop_id
        )
        
        # 4. Update events location
        await conn.execute(
            "UPDATE events SET location_id = $1 WHERE location_id = $2;", 
            keep_id, drop_id
        )
        
        # 5. Union entity aliases
        aliases = await conn.fetch(
            "SELECT alias, revealed_at_chapter FROM entity_aliases WHERE entity_id = $1;", 
            drop_id
        )
        for row in aliases:
            await conn.execute(
                """
                INSERT INTO entity_aliases (entity_id, alias, revealed_at_chapter)
                VALUES ($1, $2, $3)
                ON CONFLICT (entity_id, alias) DO UPDATE
                SET revealed_at_chapter = LEAST(entity_aliases.revealed_at_chapter, EXCLUDED.revealed_at_chapter);
                """,
                keep_id, row["alias"], row["revealed_at_chapter"]
            )
            
        # 6. Delete old aliases & identity links
        await conn.execute("DELETE FROM entity_aliases WHERE entity_id = $1;", drop_id)
        await conn.execute("DELETE FROM identity_links WHERE entity_a = $1 OR entity_b = $1;", drop_id)
        
        # 7. Delete old entity
        await conn.execute("DELETE FROM entities WHERE id = $1;", drop_id)
        
        # 8. Invalidate affected caches
        await clear_caches(conn, entity_id=keep_id)
        await clear_caches(conn, entity_id=drop_id)
        
    logger.info(f"Entity ID {drop_id} merged into ID {keep_id} successfully.")
