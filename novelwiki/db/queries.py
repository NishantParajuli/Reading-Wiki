import logging
import asyncpg
from novelwiki.db.connection import get_db_pool

logger = logging.getLogger(__name__)

async def clear_caches(
    conn: asyncpg.Connection = None,
    chapter_number: float = None,
    entity_id: int = None
):
    """
    Clears wiki_cache and query_cache tables.
    If chapter_number is specified, invalidates caches where the chapter_ceiling is >= chapter_number.
    If entity_id is specified, invalidates wiki_cache entries for that entity.
    """
    async def _execute(c):
        if chapter_number is not None:
            logger.info(f"Invalidating caches >= chapter {chapter_number}")
            await c.execute("DELETE FROM query_cache WHERE chapter_ceiling >= $1;", chapter_number)
            await c.execute("DELETE FROM wiki_cache WHERE chapter_ceiling >= $1;", chapter_number)
        elif entity_id is not None:
            logger.info(f"Invalidating wiki_cache for entity_id {entity_id}")
            await c.execute("DELETE FROM wiki_cache WHERE entity_id = $1;", entity_id)
        else:
            logger.info("Dropping all caches")
            await c.execute("DELETE FROM query_cache;")
            await c.execute("DELETE FROM wiki_cache;")

    if conn is not None:
        await _execute(conn)
    else:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await _execute(conn)
