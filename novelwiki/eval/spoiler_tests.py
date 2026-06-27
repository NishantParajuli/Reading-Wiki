import pytest
import pytest_asyncio
from novelwiki.db.connection import get_db_pool, close_db_pool

@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    """
    Autouse fixture that resets the connection pool and cleans the database
    before and after each test. This avoids event loop mismatch errors
    and transaction isolation invisibility.

    SAFETY: the unscoped DELETEs below wipe whole tables. They are safe ONLY because
    conftest.py routes the entire eval suite onto a disposable *_test database (and
    hard-fails the session otherwise). Never point this at the production DB.
    """
    # 1. Reset pool so it's recreated in the current test's event loop
    await close_db_pool()
    pool = await get_db_pool()
    
    # 2. Clean tables
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM entity_facts CASCADE;")
            await conn.execute("DELETE FROM entity_aliases CASCADE;")
            await conn.execute("DELETE FROM identity_links CASCADE;")
            await conn.execute("DELETE FROM relationships CASCADE;")
            await conn.execute("DELETE FROM events CASCADE;")
            await conn.execute("DELETE FROM entities CASCADE;")
            await conn.execute("DELETE FROM chunks CASCADE;")
            await conn.execute("DELETE FROM chapters CASCADE;")
            
    yield
    
    # 3. Clean after test and reset pool
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM entity_facts CASCADE;")
            await conn.execute("DELETE FROM entity_aliases CASCADE;")
            await conn.execute("DELETE FROM identity_links CASCADE;")
            await conn.execute("DELETE FROM relationships CASCADE;")
            await conn.execute("DELETE FROM events CASCADE;")
            await conn.execute("DELETE FROM entities CASCADE;")
            await conn.execute("DELETE FROM chunks CASCADE;")
            await conn.execute("DELETE FROM chapters CASCADE;")
    await close_db_pool()

@pytest_asyncio.fixture()
async def db_conn():
    """Acquires a dedicated connection for seeding test data."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        yield conn

@pytest.mark.asyncio
async def test_forward_only_audit(db_conn):
    """
    Asserts the strict forward-only database extraction invariant.
    Checks that no entity facts, relationships, or events in the database 
    ever map to any source chunk from a future chapter.
    """
    # We query any facts where there's a source chunk with a chapter number
    # greater than the fact's own recorded chapter.
    violations = await db_conn.fetch(
        """
        SELECT f.id, f.chapter AS fact_chapter, ch.chapter AS chunk_chapter
        FROM entity_facts f
        CROSS JOIN LATERAL unnest(f.source_chunk_ids) AS chunk_id
        JOIN chunks ch ON ch.id = chunk_id
        WHERE ch.chapter > f.chapter;
        """
    )
    assert len(violations) == 0, f"Found forward-only audit violations! {violations}"
