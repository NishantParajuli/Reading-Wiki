from __future__ import annotations

import logging
from typing import Any

from novelwiki.platform.database import get_db_pool

logger = logging.getLogger(__name__)


async def clear_caches(
    connection: Any = None,
    novel_id: int | None = None,
    chapter_number: float | None = None,
    entity_id: int | None = None,
) -> None:
    async def execute(target: Any) -> None:
        if chapter_number is not None:
            logger.info("Invalidating caches >= chapter %s (novel %s)", chapter_number, novel_id)
            await target.execute(
                "DELETE FROM query_cache WHERE chapter_ceiling >= $1 AND novel_id = $2;",
                chapter_number, novel_id,
            )
            await target.execute(
                "DELETE FROM wiki_cache WHERE chapter_ceiling >= $1 AND novel_id = $2;",
                chapter_number, novel_id,
            )
        elif entity_id is not None:
            logger.info("Invalidating wiki_cache for entity_id %s (novel %s)", entity_id, novel_id)
            await target.execute(
                "DELETE FROM wiki_cache WHERE entity_id = $1 AND novel_id = $2;",
                entity_id, novel_id,
            )
        else:
            logger.info("Dropping all caches for novel %s", novel_id)
            await target.execute("DELETE FROM query_cache WHERE novel_id = $1;", novel_id)
            await target.execute("DELETE FROM wiki_cache WHERE novel_id = $1;", novel_id)

    if connection is not None:
        await execute(connection)
        return
    pool = await get_db_pool()
    async with pool.acquire() as acquired:
        await execute(acquired)
