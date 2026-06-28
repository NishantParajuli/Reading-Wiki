"""Regression tests for the per-user shelf / library-scoping / owner-controlled tags
and tag-suggestion behaviour (multi-user bug-fix batch)."""
import pytest
import pytest_asyncio
from fastapi import HTTPException

from novelwiki.api import routes
from novelwiki.api.routes import NovelUpdate, TagSuggestion
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
async def db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM tag_suggestions;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")
            admin = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('admin@example.test', 'admin', 'Admin', 'admin', TRUE) RETURNING *;
                """
            )
            reader = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('reader@example.test', 'reader', 'Reader', 'user', TRUE) RETURNING *;
                """
            )
            # A curated global novel owned by the admin, with a shelf/tag already set on it.
            novel_id = await conn.fetchval(
                """
                INSERT INTO novels (title, owner_id, visibility, shelf, status_tags)
                VALUES ('Shared Epic', $1, 'global', 'completed', ARRAY['finished'])
                RETURNING id;
                """,
                admin["id"],
            )
            # Owner's library membership (mirrors create/import flow + migration seeding).
            await conn.execute(
                "INSERT INTO library_entries (user_id, novel_id, shelf) VALUES ($1, $2, 'completed');",
                admin["id"], novel_id,
            )
    yield {"admin": dict(admin), "reader": dict(reader), "novel_id": novel_id}
    await _reset_pool()


# ── Bug #2: a shared/global novel is NOT in a fresh reader's library ──────────
@pytest.mark.asyncio
async def test_global_novel_not_in_library_until_added(db):
    lib = await routes.api_list_novels(user=db["reader"])
    assert db["novel_id"] not in [n["id"] for n in lib], "global novel leaked into reader's library"

    await routes.api_add_to_library(db["novel_id"], user=db["reader"])
    lib = await routes.api_list_novels(user=db["reader"])
    assert db["novel_id"] in [n["id"] for n in lib], "added novel should appear in library"


# ── Bug #1: shelf is per-user; the novel's legacy shelf never leaks to readers ─
@pytest.mark.asyncio
async def test_shelf_is_per_user(db):
    await routes.api_add_to_library(db["novel_id"], user=db["reader"])
    # Reader hasn't shelved it — even though the novel + owner say "completed".
    got = await routes.api_get_novel(db["novel_id"], user=db["reader"])
    assert got["shelf"] is None

    await routes.api_update_novel(db["novel_id"], NovelUpdate(shelf="reading"), user=db["reader"])
    assert (await routes.api_get_novel(db["novel_id"], user=db["reader"]))["shelf"] == "reading"
    # Admin's own shelf is untouched by the reader's choice.
    assert (await routes.api_get_novel(db["novel_id"], user=db["admin"]))["shelf"] == "completed"


# ── Bug #3: status tags are owner/admin-only novel metadata ───────────────────
@pytest.mark.asyncio
async def test_reader_cannot_edit_tags(db):
    with pytest.raises(HTTPException) as exc:
        await routes.api_update_novel(
            db["novel_id"], NovelUpdate(status_tags=["ongoing"]), user=db["reader"]
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_radio_group_rejects_two_exclusive_tags(db):
    with pytest.raises(HTTPException) as exc:
        await routes.api_update_novel(
            db["novel_id"], NovelUpdate(status_tags=["ongoing", "finished"]), user=db["admin"]
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_owner_sets_tags_visible_to_reader(db):
    await routes.api_update_novel(
        db["novel_id"], NovelUpdate(status_tags=["ongoing", "fantasy", "bogus"]), user=db["admin"]
    )
    got = await routes.api_get_novel(db["novel_id"], user=db["reader"])
    assert set(got["status_tags"]) == {"ongoing", "fantasy"}  # whitelist drops "bogus"
    assert got["can_suggest_tags"] is True


# ── Bug #3: tag suggestions flow ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tag_suggestion_accept_applies_to_novel(db):
    await routes.api_suggest_tags(
        db["novel_id"], TagSuggestion(tags=["ongoing", "romance"], note="please"), user=db["reader"]
    )
    pending = await routes.api_list_tag_suggestions(db["novel_id"], user=db["admin"])
    assert len(pending) == 1 and set(pending[0]["tags"]) == {"ongoing", "romance"}

    await routes.api_accept_tag_suggestion(db["novel_id"], pending[0]["id"], user=db["admin"])
    got = await routes.api_get_novel(db["novel_id"], user=db["admin"])
    assert set(got["status_tags"]) == {"ongoing", "romance"}
    # No longer pending.
    assert await routes.api_list_tag_suggestions(db["novel_id"], user=db["admin"]) == []


@pytest.mark.asyncio
async def test_owner_cannot_suggest_tags_on_own_novel(db):
    with pytest.raises(HTTPException) as exc:
        await routes.api_suggest_tags(db["novel_id"], TagSuggestion(tags=["ongoing"]), user=db["admin"])
    assert exc.value.status_code == 400
