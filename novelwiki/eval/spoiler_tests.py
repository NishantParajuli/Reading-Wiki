import asyncio
import pytest
import asyncpg
import pytest_asyncio
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.retrieval.tools import (
    get_entity_profile, get_timeline, get_relationships, resolve_entity, list_entities
)

@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    """
    Autouse fixture that resets the connection pool and cleans the database 
    before and after each test. This avoids event loop mismatch errors 
    and transaction isolation invisibility.
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
async def test_spoiler_ceiling_isolation(db_conn):
    """
    Verifies that facts are strictly invisible below their revealed chapter.
    """
    # 1. Seed mock data (committed so pool connections can read it)
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (1.0, 'Intro', 'Once upon a time...');")
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (10.0, 'The Reveal', 'The dark sword is actually cursed.');")
    
    # Seed entity
    ent_id = await db_conn.fetchval(
        """
        INSERT INTO entities (canonical_name, type, first_seen_chapter) 
        VALUES ('Dark Sword', 'item', 1.0) 
        RETURNING id;
        """
    )
    
    # Fact revealed at Ch 1.0 (Safe)
    await db_conn.execute(
        """
        INSERT INTO entity_facts (entity_id, chapter, fact_type, content) 
        VALUES ($1, 1.0, 'description', 'A legendary sword of obsidian color.');
        """,
        ent_id
    )
    
    # Fact revealed at Ch 10.0 (Secret)
    await db_conn.execute(
        """
        INSERT INTO entity_facts (entity_id, chapter, fact_type, content) 
        VALUES ($1, 10.0, 'secret', 'The sword carries the cursed soul of the demon king.');
        """,
        ent_id
    )
    
    # ── ASSERT AT CEILING = 9.0 ──
    profile_before = await get_entity_profile(ent_id, 9.0)
    assert profile_before is not None
    assert len(profile_before["facts"]) == 1
    assert "obsidian" in profile_before["facts"][0]["content"]
    assert "cursed" not in "".join([f["content"] for f in profile_before["facts"]])
    
    # ── ASSERT AT CEILING = 10.0 ──
    profile_after = await get_entity_profile(ent_id, 10.0)
    assert profile_after is not None
    assert len(profile_after["facts"]) == 2
    contents = "".join([f["content"] for f in profile_after["facts"]])
    assert "obsidian" in contents
    assert "demon king" in contents

@pytest.mark.asyncio
async def test_identity_reveal_folding(db_conn):
    """
    Verifies that dual personas ('Masked Man' and 'Prince X') remain completely
    unlinked below the reveal chapter, but fold their profiles and aliases
    exactly at or above the reveal chapter.
    """
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (1.0, 'Intro', 'A masked man appears.');")
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (5.0, 'Prince Entry', 'Prince X enters.');")
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (10.0, 'Reveal', 'Prince X unmasks himself.');")
    
    # Persona A: Masked Man
    id_masked = await db_conn.fetchval(
        "INSERT INTO entities (canonical_name, type, first_seen_chapter) VALUES ('Masked Man', 'character', 1.0) RETURNING id;"
    )
    await db_conn.execute(
        "INSERT INTO entity_facts (entity_id, chapter, fact_type, content) VALUES ($1, 1.0, 'status', 'Fights with dual daggers.');",
        id_masked
    )
    await db_conn.execute(
        "INSERT INTO entity_aliases (entity_id, alias, revealed_at_chapter) VALUES ($1, 'Silent Shadow', 1.0);",
        id_masked
    )
    
    # Persona B: Prince X
    id_prince = await db_conn.fetchval(
        "INSERT INTO entities (canonical_name, type, first_seen_chapter) VALUES ('Prince X', 'character', 5.0) RETURNING id;"
    )
    await db_conn.execute(
        "INSERT INTO entity_facts (entity_id, chapter, fact_type, content) VALUES ($1, 5.0, 'trait', 'Heir to the Solis throne.');",
        id_prince
    )
    
    # Identity Link: Masked Man is Prince X, revealed at Ch 10.0
    await db_conn.execute(
        "INSERT INTO identity_links (entity_a, entity_b, revealed_at_chapter, note) VALUES ($1, $2, 10.0, 'Prince X is revealed as Masked Man');",
        id_masked, id_prince
    )
    
    # ── ASSERTION AT CEILING = 9.0 (Before Reveal) ──
    # Profiles must remain completely isolated
    profile_masked = await get_entity_profile(id_masked, 9.0)
    assert len(profile_masked["facts"]) == 1
    assert "dual daggers" in profile_masked["facts"][0]["content"]
    assert "Solis" not in "".join([f["content"] for f in profile_masked["facts"]])
    assert "Silent Shadow" in profile_masked["aliases"]
    
    profile_prince = await get_entity_profile(id_prince, 9.0)
    assert len(profile_prince["facts"]) == 1
    assert "Solis" in profile_prince["facts"][0]["content"]
    assert "dual daggers" not in "".join([f["content"] for f in profile_prince["facts"]])
    
    # Bidirectional entity resolution isolation
    res_masked = await resolve_entity("Prince X", 9.0)
    assert len(res_masked) == 1
    assert res_masked[0]["id"] == id_prince
    assert id_masked not in res_masked[0]["linked_ids"]
    
    # ── ASSERTION AT CEILING = 10.0 (After Reveal) ──
    # Profiles must cleanly merge/fold
    profile_masked_after = await get_entity_profile(id_masked, 10.0)
    assert len(profile_masked_after["facts"]) == 2
    all_contents = "".join([f["content"] for f in profile_masked_after["facts"]])
    assert "dual daggers" in all_contents
    assert "Solis" in all_contents
    
    # Combined alias lists
    assert "Silent Shadow" in profile_masked_after["aliases"]
    
    # Check timeline merging
    timeline = await get_timeline(id_masked, 10.0)
    assert len(timeline) == 2
    assert timeline[0]["chapter"] == 1.0
    assert timeline[1]["chapter"] == 5.0
    
    # Bidirectional entity resolution linking
    res_reveal = await resolve_entity("Prince X", 10.0)
    assert id_masked in res_reveal[0]["linked_ids"]
    assert id_prince in res_reveal[0]["linked_ids"]

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
