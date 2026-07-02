import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, HTTPException

import novelwiki.db.connection as db_connection
from novelwiki.api import routes
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def boundary_db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM query_cache;")
            await conn.execute("DELETE FROM wiki_cache;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")

            owner = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('owner@example.test', 'owner', 'Owner', 'user', TRUE)
                RETURNING *;
                """
            )
            reader = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('reader@example.test', 'reader', 'Reader', 'user', TRUE)
                RETURNING *;
                """
            )
            other = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('other@example.test', 'other', 'Other', 'user', TRUE)
                RETURNING *;
                """
            )
            novel_id = await conn.fetchval(
                """
                INSERT INTO novels (title, owner_id, visibility, codex_enabled)
                VALUES ('Spoiler Test', $1, 'public', TRUE)
                RETURNING id;
                """,
                owner["id"],
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
            await conn.execute(
                """
                INSERT INTO reading_progress (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct)
                VALUES ($1, $2, 1, 1, 0);
                """,
                reader["id"], novel_id,
            )

            hero_id = await conn.fetchval(
                """
                INSERT INTO entities (novel_id, canonical_name, type, description, first_seen_chapter)
                VALUES ($1, 'Hero', 'character', 'Visible hero', 1)
                RETURNING id;
                """,
                novel_id,
            )
            mask_id = await conn.fetchval(
                """
                INSERT INTO entities (novel_id, canonical_name, type, description, first_seen_chapter)
                VALUES ($1, 'Masked Stranger', 'character', 'A visible mystery', 1)
                RETURNING id;
                """,
                novel_id,
            )
            future_id = await conn.fetchval(
                """
                INSERT INTO entities (novel_id, canonical_name, type, description, first_seen_chapter)
                VALUES ($1, 'Future Villain', 'character', 'Future spoiler', 3)
                RETURNING id;
                """,
                novel_id,
            )
            true_id = await conn.fetchval(
                """
                INSERT INTO entities (novel_id, canonical_name, type, description, first_seen_chapter)
                VALUES ($1, 'True Name', 'character', 'Future identity', 3)
                RETURNING id;
                """,
                novel_id,
            )
            await conn.execute(
                """
                INSERT INTO entity_facts (novel_id, entity_id, chapter, fact_type, content)
                VALUES ($1, $2, 1, 'status', 'Hero is known.'),
                       ($1, $3, 3, 'status', 'Future villain arrives.');
                """,
                novel_id, hero_id, future_id,
            )
            await conn.execute(
                """
                INSERT INTO relationships (novel_id, source_id, target_id, chapter, relation_type, content)
                VALUES ($1, $2, $3, 3, 'enemy', 'They become enemies.');
                """,
                novel_id, hero_id, future_id,
            )
            await conn.execute(
                """
                INSERT INTO events (novel_id, chapter, description, participants)
                VALUES ($1, 1, 'Hero starts the journey.', $2),
                       ($1, 3, 'Future villain appears.', $3);
                """,
                novel_id, [hero_id], [future_id],
            )
            await conn.execute(
                """
                INSERT INTO identity_links (novel_id, entity_a, entity_b, revealed_at_chapter, note)
                VALUES ($1, $2, $3, 3, 'The stranger is named.');
                """,
                novel_id, mask_id, true_id,
            )
            await conn.execute(
                """
                INSERT INTO wiki_cache (novel_id, entity_id, chapter_ceiling, rendered_md, model, evidence_ids)
                VALUES ($1, $2, 1, 'cached hero profile', 'test', '{}'::jsonb);
                """,
                novel_id, hero_id,
            )

    yield {
        "pool": pool,
        "owner": dict(owner),
        "reader": dict(reader),
        "other": dict(other),
        "novel_id": novel_id,
        "hero_id": hero_id,
        "mask_id": mask_id,
        "future_id": future_id,
        "true_id": true_id,
    }
    await _reset_pool()


@pytest.mark.asyncio
async def test_codex_routes_clamp_requested_ceiling_to_trusted_progress(boundary_db):
    novel_id = boundary_db["novel_id"]
    reader = boundary_db["reader"]

    stats = await routes.api_meta_stats(novel_id, ceiling=3, user=reader)
    assert stats["effective_ceiling"] == 1.0
    assert stats["allowed_ceiling"] == 1.0
    assert stats["ceiling_clamped"] is True
    assert stats["entities_revealed"] == 2
    assert stats["facts_known"] == 1
    assert stats["relationships_known"] == 0

    entities = await routes.api_list_entities(novel_id, ceiling=3, user=reader)
    assert {e["canonical_name"] for e in entities} == {"Hero", "Masked Stranger"}

    assert await routes.api_resolve_entity(novel_id, name="Future Villain", ceiling=3, user=reader) == []

    profile = await routes.api_get_entity_profile(novel_id, boundary_db["hero_id"], ceiling=3, user=reader)
    assert profile["rendered_md"] == "cached hero profile"
    assert [f["content"] for f in profile["facts"]] == ["Hero is known."]

    with pytest.raises(HTTPException) as exc:
        await routes.api_get_entity_profile(novel_id, boundary_db["future_id"], ceiling=3, user=reader)
    assert exc.value.status_code == 404

    assert await routes.api_get_relationships(novel_id, boundary_db["hero_id"], ceiling=3, user=reader) == []
    timeline = await routes.api_get_timeline(novel_id, boundary_db["hero_id"], ceiling=3, user=reader)
    assert {t["content"] for t in timeline} == {"Hero is known.", "Hero starts the journey."}
    assert await routes.api_get_identities(novel_id, boundary_db["mask_id"], ceiling=3, user=reader) == []


@pytest.mark.asyncio
async def test_ask_uses_effective_ceiling(boundary_db, monkeypatch):
    captured = {}

    class FakeBm25:
        async def ensure_loaded(self):
            return None

    async def fake_answer(novel_id, question, chapter_ceiling):
        captured["novel_id"] = novel_id
        captured["question"] = question
        captured["chapter_ceiling"] = chapter_ceiling
        return {"answer": "safe", "citations": [], "evidence_ids": {}}

    monkeypatch.setattr(routes, "get_bm25_manager", lambda _novel_id: FakeBm25())
    monkeypatch.setattr(routes, "answer_question", fake_answer)

    resp = await routes.ask_question(
        boundary_db["novel_id"],
        routes.AskRequest(question="What happens later?", ceiling=3),
        user=boundary_db["reader"],
    )

    assert captured["chapter_ceiling"] == 1.0
    assert resp.effective_ceiling == 1.0
    assert resp.allowed_ceiling == 1.0
    assert resp.ceiling_clamped is True


@pytest.mark.asyncio
async def test_progress_put_cannot_unlock_future_codex_but_chapter_read_can(boundary_db):
    novel_id = boundary_db["novel_id"]
    reader = boundary_db["reader"]

    await routes.api_set_progress(
        novel_id,
        routes.ProgressUpdate(last_chapter=3, scroll_pct=0.5),
        user=reader,
    )
    stats = await routes.api_meta_stats(novel_id, ceiling=3, user=reader)
    assert stats["effective_ceiling"] == 1.0

    async with boundary_db["pool"].acquire() as conn:
        assert await conn.fetchval(
            "SELECT max_chapter_read FROM reading_progress WHERE user_id = $1 AND novel_id = $2;",
            reader["id"], novel_id,
        ) == 1

    await routes.api_get_chapter(novel_id, 3, BackgroundTasks(), user=reader)
    stats = await routes.api_meta_stats(novel_id, ceiling=3, user=reader)
    assert stats["effective_ceiling"] == 3.0

    entities = await routes.api_list_entities(novel_id, ceiling=3, user=reader)
    assert "Future Villain" in {e["canonical_name"] for e in entities}


@pytest.mark.asyncio
async def test_future_root_entity_cannot_leak_traversal_data(boundary_db):
    novel_id = boundary_db["novel_id"]
    reader = boundary_db["reader"]

    async with boundary_db["pool"].acquire() as conn:
        await conn.execute(
            """
            INSERT INTO relationships (novel_id, source_id, target_id, chapter, relation_type, content)
            VALUES ($1, $2, $3, 1, 'seen-too-early', 'Invalid future-root relationship.');
            """,
            novel_id, boundary_db["future_id"], boundary_db["hero_id"],
        )
        await conn.execute(
            """
            INSERT INTO entity_facts (novel_id, entity_id, chapter, fact_type, content)
            VALUES ($1, $2, 1, 'invalid', 'Invalid future-root fact.');
            """,
            novel_id, boundary_db["future_id"],
        )
        await conn.execute(
            """
            UPDATE identity_links
            SET revealed_at_chapter = 1
            WHERE novel_id = $1 AND entity_b = $2;
            """,
            novel_id, boundary_db["true_id"],
        )

    assert await routes.api_get_relationships(novel_id, boundary_db["future_id"], ceiling=3, user=reader) == []
    assert await routes.api_get_timeline(novel_id, boundary_db["future_id"], ceiling=3, user=reader) == []
    assert await routes.api_get_identities(novel_id, boundary_db["true_id"], ceiling=3, user=reader) == []
