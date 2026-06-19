import json
import pytest
import asyncpg
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.db.queries import clear_caches
from novelwiki.ingest.chunk import chunk_chapter
from novelwiki.ingest.embed import embed_missing_chunks
from novelwiki.ingest.extract import extract_knowledge_for_chapter
from novelwiki.ingest.link import merge_entities
from novelwiki.retrieval.tools import get_entity_profile
from novelwiki.agent.orchestrator import answer_question
from novelwiki.api.routes import api_get_entity_profile

# ── Clean up Database after each test ──
# SAFETY: the unscoped DELETEs below wipe whole tables. They are safe ONLY because
# conftest.py routes the eval suite onto a disposable *_test database (and hard-fails
# the session otherwise). Never point this at the production DB.
@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    await close_db_pool()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM query_cache CASCADE;")
            await conn.execute("DELETE FROM wiki_cache CASCADE;")
            await conn.execute("DELETE FROM entity_facts CASCADE;")
            await conn.execute("DELETE FROM entity_aliases CASCADE;")
            await conn.execute("DELETE FROM identity_links CASCADE;")
            await conn.execute("DELETE FROM relationships CASCADE;")
            await conn.execute("DELETE FROM events CASCADE;")
            await conn.execute("DELETE FROM extraction_state CASCADE;")
            await conn.execute("DELETE FROM entities CASCADE;")
            await conn.execute("DELETE FROM chunks CASCADE;")
            await conn.execute("DELETE FROM chapters CASCADE;")
    yield
    await close_db_pool()

@pytest_asyncio.fixture()
async def db_conn():
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        yield conn

@pytest.mark.asyncio
@patch("novelwiki.agent.orchestrator.call_chat_completion")
@patch("novelwiki.retrieval.dense.get_embedding")
async def test_agentic_qa_orchestrator_and_cache(mock_get_embedding, mock_call_chat_completion, db_conn):
    """
    Verifies the end-to-end Pro-Flash agentic chatbot loop:
    1. Orchestrator plans, decides tool calls, distills, synthesizes, and verifies grounding.
    2. answer_question returns {answer, citations, evidence_ids}.
    3. Answers are cached and retrieved directly on subsequent calls.
    """
    mock_get_embedding.return_value = [0.1] * settings.EMBED_DIM

    # Mock LLM calls in order:
    # 1. Pro initial plan
    # 2. Pro decide -> "DONE"
    # 3. Pro synthesis
    # 4. Flash verification (supported)
    mock_call_chat_completion.side_effect = [
        "Plan: resolve Prince X then look up residence.",          # Pro plan
        "DONE",                                                      # Pro decide (iteration 1)
        "This is a verified mock answer about Prince X.",           # Pro synthesis
        '{"unsupported": false, "flags": []}',                       # Flash verification
    ]

    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (1.0, 'Prologue', 'Prince X resides in the solar capital Solis.');")
    await db_conn.execute("INSERT INTO chunks (chapter, chunk_index, text, embedding) VALUES (1.0, 0, 'Prince X resides in Solis.', $1::vector);", "[" + ",".join(["0.1"] * settings.EMBED_DIM) + "]")

    # First call: triggers full agent loop
    ans1 = await answer_question("Where does Prince X reside?", 1.0)
    assert "Prince X" in ans1["answer"]
    assert "citations" in ans1 and "evidence_ids" in ans1
    assert mock_call_chat_completion.call_count == 4

    # Check cache has entry
    row = await db_conn.fetchrow("SELECT answer_md FROM query_cache WHERE chapter_ceiling = 1.0;")
    assert row is not None
    assert row["answer_md"] == "This is a verified mock answer about Prince X."

    # Second call: returns cached answer immediately (no new LLM calls)
    ans2 = await answer_question("Where does Prince X reside?", 1.0)
    assert ans2["answer"] == ans1["answer"]
    assert mock_call_chat_completion.call_count == 4  # unchanged


@pytest.mark.asyncio
@patch("novelwiki.agent.orchestrator.call_chat_completion")
async def test_orchestrator_respects_iteration_cap(mock_call_chat_completion, db_conn):
    """Cost guard: if the planner never says DONE, the loop must stop at MAX_ITERATIONS."""
    decide_calls = {"n": 0}

    def dispatcher(model, messages, temperature=0.0, response_format=None):
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if "outline the retrieval subgoals" in user:
            return "plan"
        if "Decide the next tool calls" in user:
            decide_calls["n"] += 1
            return '[{"tool": "list_entities", "args": {}}]'  # never DONE
        if "compact, faithful digest" in system:
            return "digest"
        if "Write the answer" in system:
            return "Final answer."
        if "Check the draft" in system:
            return '{"unsupported": false, "flags": []}'
        return ""

    mock_call_chat_completion.side_effect = dispatcher

    result = await answer_question("Tell me everything.", 1.0)
    assert result["answer"] == "Final answer."
    assert decide_calls["n"] == settings.MAX_ITERATIONS

@pytest.mark.asyncio
@patch("novelwiki.api.routes.call_chat_completion")
async def test_wiki_cache_lookup_fast_path(mock_call_chat_completion, db_conn):
    """
    Verifies that the /entity/{id} endpoint:
    1. Synthesizes and caches beautiful Markdown wiki profile on first hit (cache miss).
    2. Directly returns cached profile on subsequent hits (cache hit).
    """
    mock_call_chat_completion.return_value = "### Prince X\n\nPrince X is the crown heir."

    # Seed data
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (1.0, 'Intro', 'A prince is born.');")
    ent_id = await db_conn.fetchval("INSERT INTO entities (canonical_name, type, first_seen_chapter) VALUES ('Prince X', 'character', 1.0) RETURNING id;")
    await db_conn.execute("INSERT INTO entity_facts (entity_id, chapter, fact_type, content) VALUES ($1, 1.0, 'status', 'Crown heir.');", ent_id)

    # First fetch: Cache Miss -> Synthesizes via LLM
    profile1 = await api_get_entity_profile(ent_id, 1.0)
    assert "Prince X" in profile1["canonical_name"]
    assert profile1["rendered_md"] == "### Prince X\n\nPrince X is the crown heir."
    assert mock_call_chat_completion.call_count == 1

    # Second fetch: Cache Hit -> Returns cached immediately
    profile2 = await api_get_entity_profile(ent_id, 1.0)
    assert profile2["rendered_md"] == "### Prince X\n\nPrince X is the crown heir."
    assert mock_call_chat_completion.call_count == 1  # Count remains same

@pytest.mark.asyncio
async def test_cache_invalidation(db_conn):
    """
    Verifies that clear_caches correctly deletes cache entries:
    - Invalidate ceiling-specific cache records.
    - Invalidate entity-specific profile render caches.
    """
    # Seed caches
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (1.0, 'Intro', 'Start.');")
    ent_id = await db_conn.fetchval("INSERT INTO entities (canonical_name, type, first_seen_chapter) VALUES ('Prince X', 'character', 1.0) RETURNING id;")
    
    await db_conn.execute("INSERT INTO query_cache (query_hash, chapter_ceiling, answer_md, evidence_ids) VALUES ('q1', 1.0, 'Ans 1', '{}');")
    await db_conn.execute("INSERT INTO query_cache (query_hash, chapter_ceiling, answer_md, evidence_ids) VALUES ('q2', 5.0, 'Ans 2', '{}');")
    await db_conn.execute("INSERT INTO wiki_cache (entity_id, chapter_ceiling, rendered_md, model, evidence_ids) VALUES ($1, 1.0, 'Profile 1', 'model', '{}');", ent_id)
    await db_conn.execute("INSERT INTO wiki_cache (entity_id, chapter_ceiling, rendered_md, model, evidence_ids) VALUES ($1, 5.0, 'Profile 2', 'model', '{}');", ent_id)

    # Clear cache >= chapter 5.0 (should invalidate 5.0 entries but keep 1.0)
    await clear_caches(db_conn, chapter_number=5.0)
    
    rows_query = await db_conn.fetch("SELECT chapter_ceiling FROM query_cache ORDER BY chapter_ceiling;")
    assert len(rows_query) == 1
    assert float(rows_query[0]["chapter_ceiling"]) == 1.0
    
    rows_wiki = await db_conn.fetch("SELECT chapter_ceiling FROM wiki_cache ORDER BY chapter_ceiling;")
    assert len(rows_wiki) == 1
    assert float(rows_wiki[0]["chapter_ceiling"]) == 1.0

    # Clear specific entity caches (should invalidate Prince X's 1.0 wiki_cache entry)
    await clear_caches(db_conn, entity_id=ent_id)
    
    rows_wiki2 = await db_conn.fetch("SELECT * FROM wiki_cache;")
    assert len(rows_wiki2) == 0

@pytest.mark.asyncio
async def test_text_chunker_pipeline(db_conn):
    """
    Verifies that the within-chapter text chunker runs correctly
    and handles chapter isolation (Invariant 6).
    """
    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (1.0, 'Intro', 'This is paragraph one.\n\nThis is paragraph two.');")
    
    count = await chunk_chapter(1.0)
    assert count > 0
    
    chunks = await db_conn.fetch("SELECT * FROM chunks WHERE chapter = 1.0;")
    assert len(chunks) == count
    for c in chunks:
        assert c["chapter"] == 1.0

@pytest.mark.asyncio
@patch("novelwiki.ingest.embed.get_embeddings_batch")
async def test_embedding_pipeline(mock_get_embeddings_batch, db_conn):
    """
    Verifies that the embedding generator processes only chunks missing embeddings
    and stores them correctly.
    """
    mock_get_embeddings_batch.return_value = [[0.2] * settings.EMBED_DIM]

    await db_conn.execute("INSERT INTO chapters (number, title, clean_text) VALUES (1.0, 'Intro', 'Passage text.');")
    await db_conn.execute("INSERT INTO chunks (chapter, chunk_index, text) VALUES (1.0, 0, 'Passage text.');")
    
    cnt = await embed_missing_chunks()
    assert cnt == 1
    
    emb = await db_conn.fetchval("SELECT embedding FROM chunks WHERE chapter = 1.0 AND chunk_index = 0;")
    assert emb is not None
    # If returned as raw pgvector string '[v1,v2,...]', parse it first
    if isinstance(emb, str):
        emb_list = json.loads(emb)
    else:
        emb_list = list(emb)
    assert len(emb_list) == settings.EMBED_DIM
