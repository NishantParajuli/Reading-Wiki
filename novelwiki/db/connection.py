import asyncpg
import logging
from novelwiki.config.settings import settings

logger = logging.getLogger(__name__)

_pool = None

async def init_db_pool():
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                settings.DATABASE_URL,
                min_size=1,
                max_size=10
            )
            logger.info("Database pool initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise e
    return _pool

async def close_db_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")

async def get_db_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        await init_db_pool()
    return _pool
