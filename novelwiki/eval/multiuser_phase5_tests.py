import pytest
import pytest_asyncio
from fastapi import HTTPException

from novelwiki.api import routes
from novelwiki.api.routes import ContributionAccept
import novelwiki.db.connection as db_connection
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def phase5_db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM contributions;")
            await conn.execute("DELETE FROM chapter_overlays;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")

            owner = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('owner@example.test', 'owner', 'Owner', 'user', TRUE)
                RETURNING *;
                """
            )
            contributor = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('reader@example.test', 'reader', 'Reader', 'user', TRUE)
                RETURNING *;
                """
            )
            novel_id = await conn.fetchval(
                """
                INSERT INTO novels (title, owner_id, visibility, contribution_policy)
                VALUES ('Merge Test', $1, 'public', 'manual')
                RETURNING id;
                """,
                owner["id"],
            )
            await conn.execute(
                """
                INSERT INTO chapters (novel_id, number, title, content, content_version, translation_status)
                VALUES ($1, 1, 'One', 'base v2', 2, 'done');
                """,
                novel_id,
            )

    yield {"owner": dict(owner), "contributor": dict(contributor), "novel_id": novel_id}
    await _reset_pool()


@pytest.mark.asyncio
async def test_conflicted_contribution_requires_resolved_content(phase5_db):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        cid = await conn.fetchval(
            """
            INSERT INTO contributions (novel_id, from_user_id, chapter, content, base_version, status)
            VALUES ($1, $2, 1, 'stale proposal', 1, 'pending')
            RETURNING id;
            """,
            phase5_db["novel_id"], phase5_db["contributor"]["id"],
        )

    with pytest.raises(HTTPException) as exc:
        await routes.api_accept_contribution(phase5_db["novel_id"], cid, user=phase5_db["owner"])
    assert exc.value.status_code == 409

    async with pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT content FROM chapters WHERE novel_id = $1 AND number = 1;",
            phase5_db["novel_id"],
        ) == "base v2"

    await routes.api_accept_contribution(
        phase5_db["novel_id"],
        cid,
        ContributionAccept(content="resolved merge"),
        user=phase5_db["owner"],
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT c.content, c.content_version, k.status, k.content AS accepted_content
            FROM chapters c JOIN contributions k ON k.id = $2
            WHERE c.novel_id = $1 AND c.number = 1;
            """,
            phase5_db["novel_id"], cid,
        )
    assert row["content"] == "resolved merge"
    assert row["content_version"] == 3
    assert row["status"] == "accepted"
    assert row["accepted_content"] == "resolved merge"


@pytest.mark.asyncio
async def test_self_translate_without_source_text_does_not_reserve_quota(phase5_db, monkeypatch):
    calls = 0

    async def fake_reserve(*_args, **_kwargs):
        nonlocal calls
        calls += 1

    monkeypatch.setattr(routes.quota, "check_and_reserve", fake_reserve)

    with pytest.raises(HTTPException) as exc:
        await routes.api_self_translate(phase5_db["novel_id"], 1.0, user=phase5_db["contributor"])

    assert exc.value.status_code == 409
    assert calls == 0
