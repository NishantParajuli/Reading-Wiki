from __future__ import annotations

from novelwiki.platform.database import get_db_pool
from novelwiki.platform.config import settings


async def prune_orphan_entities(novel_id: int) -> int:
    """Remove entities omitted by a completed v2 re-extraction of their first chapter."""
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        result = await connection.execute(
            """
            DELETE FROM entities e
            WHERE e.novel_id=$1
              AND EXISTS (
                SELECT 1 FROM extraction_state x
                WHERE x.novel_id=e.novel_id AND x.chapter=e.first_seen_chapter
                  AND x.pipeline_version=$2
              )
              AND NOT EXISTS (SELECT 1 FROM entity_activity a WHERE a.entity_id=e.id)
              AND NOT EXISTS (SELECT 1 FROM entity_descriptions d WHERE d.entity_id=e.id)
              AND NOT EXISTS (SELECT 1 FROM entity_facts f WHERE f.entity_id=e.id)
              AND NOT EXISTS (SELECT 1 FROM relationships r WHERE r.source_id=e.id OR r.target_id=e.id)
              AND NOT EXISTS (SELECT 1 FROM events v WHERE v.location_id=e.id OR e.id=ANY(v.participants))
              AND NOT EXISTS (SELECT 1 FROM identity_links i WHERE i.entity_a=e.id OR i.entity_b=e.id)
              AND NOT EXISTS (SELECT 1 FROM entity_state_transitions s
                              WHERE s.entity_id=e.id OR s.perspective_entity_id=e.id)
              AND NOT EXISTS (SELECT 1 FROM relationship_state_transitions s
                              WHERE s.source_id=e.id OR s.target_id=e.id)
              AND NOT EXISTS (SELECT 1 FROM plot_thread_updates u WHERE e.id=ANY(u.participants));
            """,
            novel_id, settings.CODEX_PIPELINE_VERSION,
        )
    return int(result.rsplit(" ", 1)[-1])


async def reset_structured_codex(novel_id: int) -> None:
    """Delete derived Codex knowledge while preserving source chapters/chunks."""
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock($1::bigint);",
                7_200_000_000_000_000 + int(novel_id),
            )
            for table in (
                "query_cache", "wiki_cache", "extraction_contexts", "plot_thread_updates",
                "plot_threads", "relationship_state_transitions", "entity_state_transitions",
                "entity_activity", "memory_segments", "chapter_summaries", "extraction_state",
                "events", "relationships", "entity_facts", "identity_links",
                "entity_aliases", "entity_descriptions", "entities",
            ):
                await connection.execute(
                    f"DELETE FROM {table} WHERE novel_id=$1;", novel_id
                )
