"""Regression tests for Batch 7: read-side AI cost controls + BM25 event-loop offload.

Covers the denial-of-wallet guards on the uncached AI read paths (`/ask`, entity-profile
synthesis): length caps, verified-email spend gate, per-user hourly rate limit, concurrency
slots, tool-fanout clamps, and that cache hits stay free. Also asserts BM25's synchronous
search is offloaded off the event loop.
"""
import asyncio
import time

import numpy as np
import pytest
import pytest_asyncio
from fastapi import HTTPException

import novelwiki.db.connection as db_connection
from novelwiki import ai_limits
from novelwiki.agent import orchestrator
from novelwiki.agent.orchestrator import compute_query_hash
from novelwiki.api import routes
from novelwiki.auth import rate_limit
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.retrieval.bm25 import BM25Manager


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


class _FakeBm25:
    async def ensure_loaded(self):
        return None


@pytest_asyncio.fixture()
async def ai_db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM query_cache;")
            await conn.execute("DELETE FROM wiki_cache;")
            await conn.execute("DELETE FROM ai_request_locks;")
            await conn.execute("DELETE FROM auth_rate_limits;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")

            verified = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('v@example.test', 'verified', 'Verified', 'user', TRUE)
                RETURNING *;
                """
            )
            unverified = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('u@example.test', 'unverified', 'Unverified', 'user', FALSE)
                RETURNING *;
                """
            )
            novel_id = await conn.fetchval(
                """
                INSERT INTO novels (title, owner_id, visibility, codex_enabled)
                VALUES ('AI Cost Test', $1, 'public', TRUE)
                RETURNING id;
                """,
                verified["id"],
            )
            await conn.executemany(
                """
                INSERT INTO chapters (novel_id, number, title, content, translation_status)
                VALUES ($1, $2, $3, $4, 'done');
                """,
                [
                    (novel_id, 1, "One", "chapter one"),
                    (novel_id, 2, "Two", "chapter two"),
                    (novel_id, 3, "Three", "chapter three"),
                ],
            )
            # Both readers have read up to ch.3 so the effective ceiling is 3.
            for uid in (verified["id"], unverified["id"]):
                await conn.execute(
                    """
                    INSERT INTO reading_progress (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct)
                    VALUES ($1, $2, 3, 3, 0);
                    """,
                    uid, novel_id,
                )
            entity_id = await conn.fetchval(
                """
                INSERT INTO entities (novel_id, canonical_name, type, description, first_seen_chapter)
                VALUES ($1, 'Hero', 'character', 'A hero', 1)
                RETURNING id;
                """,
                novel_id,
            )

    yield {
        "pool": pool,
        "verified": dict(verified),
        "unverified": dict(unverified),
        "novel_id": novel_id,
        "entity_id": entity_id,
    }
    await _reset_pool()


async def _seed_cached_answer(pool, novel_id: int, question: str, ceiling: float, answer: str):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO query_cache (novel_id, query_hash, chapter_ceiling, answer_md, evidence_ids, created_at)
            VALUES ($1, $2, $3, $4, '{}'::jsonb, now());
            """,
            novel_id, compute_query_hash(question), ceiling, answer,
        )


# ── Spend gate on uncached paths ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_unverified_reads_cached_ask_but_cannot_trigger_uncached(ai_db, monkeypatch):
    novel_id = ai_db["novel_id"]
    await _seed_cached_answer(ai_db["pool"], novel_id, "Who is the hero?", 3, "The hero is known.")

    # Cache hit → served without touching providers/bm25.
    def _boom(*a, **k):
        raise AssertionError("cache hit must not do provider work")

    monkeypatch.setattr(routes, "get_bm25_manager", _boom)
    monkeypatch.setattr(routes, "answer_question", _boom)

    resp = await routes.ask_question(
        novel_id, routes.AskRequest(question="Who is the hero?", ceiling=3), user=ai_db["unverified"],
    )
    assert resp.answer == "The hero is known."

    # Uncached question by the same unverified reader → 403 before any provider work.
    with pytest.raises(HTTPException) as exc:
        await routes.ask_question(
            novel_id, routes.AskRequest(question="What happens next?", ceiling=3), user=ai_db["unverified"],
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unverified_cannot_trigger_uncached_profile_synthesis(ai_db):
    with pytest.raises(HTTPException) as exc:
        await routes.api_get_entity_profile(
            ai_db["novel_id"], ai_db["entity_id"], ceiling=3, user=ai_db["unverified"],
        )
    assert exc.value.status_code == 403

    # No slot left dangling after the rejection.
    async with ai_db["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM ai_request_locks;") == 0


# ── Length cap ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overlong_query_rejected_before_provider(ai_db, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must reject before any provider work")

    monkeypatch.setattr(routes, "get_bm25_manager", _boom)
    monkeypatch.setattr(routes, "answer_question", _boom)

    long_q = "a" * (settings.ASK_MAX_QUERY_CHARS + 1)
    with pytest.raises(HTTPException) as exc:
        await routes.ask_question(
            ai_db["novel_id"], routes.AskRequest(question=long_q, ceiling=3), user=ai_db["verified"],
        )
    assert exc.value.status_code == 422


# ── Cache hit is free ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_does_not_consume_rate_or_call_providers(ai_db, monkeypatch):
    novel_id = ai_db["novel_id"]
    user = ai_db["verified"]
    await _seed_cached_answer(ai_db["pool"], novel_id, "cached q", 3, "cached answer")

    called = {"rate": False, "answer": False, "bm25": False}

    async def _rate(*a, **k):
        called["rate"] = True

    def _boom_bm25(*a, **k):
        called["bm25"] = True
        raise AssertionError("cache hit must not load bm25")

    def _boom_answer(*a, **k):
        called["answer"] = True
        raise AssertionError("cache hit must not run the agent")

    monkeypatch.setattr(ai_limits, "consume_ask_rate", _rate)
    monkeypatch.setattr(routes, "get_bm25_manager", _boom_bm25)
    monkeypatch.setattr(routes, "answer_question", _boom_answer)

    resp = await routes.ask_question(
        novel_id, routes.AskRequest(question="cached q", ceiling=3), user=user,
    )
    assert resp.answer == "cached answer"
    assert called == {"rate": False, "answer": False, "bm25": False}

    # And the fixed-window bucket was never touched.
    key = rate_limit.bucket_key("ai:ask:user", str(user["id"]))
    async with ai_db["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM auth_rate_limits WHERE bucket_key = $1;", key) == 0


# ── Hourly rate limit ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_repeated_uncached_asks_eventually_429(ai_db, monkeypatch):
    monkeypatch.setattr(settings, "ASK_MAX_UNIQUE_PER_USER_HOUR", 2)
    monkeypatch.setattr(routes, "get_bm25_manager", lambda _nid: _FakeBm25())

    async def _fake_answer(novel_id, question, ceiling):
        return {"answer": "ok", "citations": [], "evidence_ids": {}}

    monkeypatch.setattr(routes, "answer_question", _fake_answer)

    user = ai_db["verified"]
    novel_id = ai_db["novel_id"]

    # Two unique uncached asks succeed; the third trips the hourly cap.
    for i in range(2):
        resp = await routes.ask_question(
            novel_id, routes.AskRequest(question=f"unique question {i}", ceiling=3), user=user,
        )
        assert resp.answer == "ok"

    with pytest.raises(HTTPException) as exc:
        await routes.ask_question(
            novel_id, routes.AskRequest(question="unique question 2", ceiling=3), user=user,
        )
    assert exc.value.status_code == 429


# ── Concurrency slot cleanup on provider failure ─────────────────────────────

@pytest.mark.asyncio
async def test_provider_exception_returns_502_and_frees_slot(ai_db, monkeypatch):
    monkeypatch.setattr(routes, "get_bm25_manager", lambda _nid: _FakeBm25())

    async def _explode(novel_id, question, ceiling):
        raise RuntimeError("provider down")

    monkeypatch.setattr(routes, "answer_question", _explode)

    with pytest.raises(HTTPException) as exc:
        await routes.ask_question(
            ai_db["novel_id"], routes.AskRequest(question="boom question", ceiling=3), user=ai_db["verified"],
        )
    assert exc.value.status_code == 502

    # The concurrency slot must have been released in the finally, not left stuck.
    async with ai_db["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM ai_request_locks;") == 0


@pytest.mark.asyncio
async def test_concurrency_limit_blocks_extra_inflight(ai_db, monkeypatch):
    monkeypatch.setattr(settings, "ASK_MAX_CONCURRENT_PER_USER", 1)
    user = ai_db["verified"]

    # Hold one slot open, then a second concurrent acquire must 429.
    async with ai_limits.concurrency_slot(user, "ask"):
        with pytest.raises(HTTPException) as exc:
            async with ai_limits.concurrency_slot(user, "ask"):
                pass
        assert exc.value.status_code == 429

    # Once the first slot is released the table is empty again.
    async with ai_db["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM ai_request_locks;") == 0


# ── Tool fan-out clamps ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_k_and_top_n_are_clamped(monkeypatch):
    captured = {}

    async def _fake_hybrid(novel_id, query, ceiling, k):
        captured["k"] = k
        return []

    async def _fake_rerank(query, hits, top_n):
        captured["top_n"] = top_n
        captured["hits_len"] = len(hits)
        return []

    monkeypatch.setattr(orchestrator, "hybrid_search", _fake_hybrid)
    monkeypatch.setattr(orchestrator, "rerank", _fake_rerank)

    await orchestrator.execute_tool(1, "hybrid_search", {"query": "q", "k": 99999}, 3)
    assert captured["k"] == settings.ASK_TOOL_MAX_K

    too_many_hits = [{"text": f"x{i}"} for i in range(settings.ASK_TOOL_MAX_RERANK_HITS + 5)]
    await orchestrator.execute_tool(1, "rerank", {"query": "q", "hits": too_many_hits, "top_n": 99999}, 3)
    assert captured["top_n"] == settings.ASK_TOOL_MAX_TOP_N
    assert captured["hits_len"] == settings.ASK_TOOL_MAX_RERANK_HITS

    # Empty query is rejected without dispatching.
    captured.clear()
    out = await orchestrator.execute_tool(1, "hybrid_search", {"query": "   "}, 3)
    assert "Error" in out and "k" not in captured

    # Overlong tool queries are rejected, not truncated and dispatched.
    out = await orchestrator.execute_tool(
        1, "hybrid_search", {"query": "x" * (settings.ASK_TOOL_MAX_QUERY_CHARS + 1)}, 3
    )
    assert "exceeds" in out and "k" not in captured


# ── BM25 offload keeps the event loop responsive ─────────────────────────────

@pytest.mark.asyncio
async def test_bm25_search_offloaded_does_not_block_event_loop(monkeypatch):
    monkeypatch.setattr(settings, "BM25_THREAD_OFFLOAD", True)
    manager = BM25Manager(1)
    manager.corpus = [{"id": 1, "chapter": 1.0, "text": "x"}]
    manager.chapter_arr = np.array([1.0])
    manager.retriever = object()

    def _slow_search(query, chapter_ceiling, k=50):
        time.sleep(0.2)   # simulates heavy synchronous tokenize/retrieve
        return []

    manager.search = _slow_search

    ticks = 0

    async def _ticker():
        nonlocal ticks
        for _ in range(60):
            await asyncio.sleep(0.005)
            ticks += 1

    results, _ = await asyncio.gather(
        manager.asearch("q", 1.0, k=5),
        _ticker(),
    )
    assert results == []
    # If the 0.2s search had blocked the loop, the ticker couldn't have progressed.
    assert ticks >= 5
