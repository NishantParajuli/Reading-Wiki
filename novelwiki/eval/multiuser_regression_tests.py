import pytest
import pytest_asyncio

import novelwiki.db.connection as db_connection
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.db import migrate_multiuser
from novelwiki.importer import commit as import_commit
from novelwiki.scraper.adapters import ChapterData
from novelwiki.scraper.runner import _persist_chapter


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def multiuser_db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM app_migrations;")
            await conn.execute("DELETE FROM contributions;")
            await conn.execute("DELETE FROM chapter_overlays;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")
    yield pool
    await _reset_pool()


@pytest.mark.asyncio
async def test_migration_marker_preserves_ownerless_private_novels_after_user_delete(multiuser_db):
    async with multiuser_db.acquire() as conn:
        admin_id = await conn.fetchval(
            """
            INSERT INTO users (email, username, display_name, role, email_verified)
            VALUES ('admin@example.test', 'admin', 'Admin', 'admin', TRUE)
            RETURNING id;
            """
        )
        victim_id = await conn.fetchval(
            """
            INSERT INTO users (email, username, display_name, role, email_verified)
            VALUES ('victim@example.test', 'victim', 'Victim', 'user', TRUE)
            RETURNING id;
            """
        )
        novel_id = await conn.fetchval(
            """
            INSERT INTO novels (title, owner_id, visibility)
            VALUES ('Private Upload', $1, 'private')
            RETURNING id;
            """,
            victim_id,
        )
        await conn.execute(
            "INSERT INTO app_migrations (name, details) VALUES ($1, '{}'::jsonb);",
            migrate_multiuser.MIGRATION_NAME,
        )
        await conn.execute("DELETE FROM users WHERE id = $1;", victim_id)

    await migrate_multiuser.maybe_migrate(allow_data_rewrite=False)

    async with multiuser_db.acquire() as conn:
        row = await conn.fetchrow("SELECT owner_id, visibility FROM novels WHERE id = $1;", novel_id)
        assert row["owner_id"] is None
        assert row["visibility"] == "private"
        assert await conn.fetchval("SELECT role FROM users WHERE id = $1;", admin_id) == "admin"


@pytest.mark.asyncio
async def test_startup_migration_refuses_legacy_without_backup_confirmation(multiuser_db):
    async with multiuser_db.acquire() as conn:
        novel_id = await conn.fetchval(
            "INSERT INTO novels (title, visibility) VALUES ('Legacy Novel', 'private') RETURNING id;"
        )

    with pytest.raises(RuntimeError, match="backup confirmation"):
        await migrate_multiuser.maybe_migrate(allow_data_rewrite=False)

    async with multiuser_db.acquire() as conn:
        row = await conn.fetchrow("SELECT owner_id, visibility FROM novels WHERE id = $1;", novel_id)
        assert row["owner_id"] is None
        assert row["visibility"] == "private"
        assert not await conn.fetchval(
            "SELECT 1 FROM app_migrations WHERE name = $1;", migrate_multiuser.MIGRATION_NAME
        )


@pytest.mark.asyncio
async def test_migration_uses_configured_admin_email(multiuser_db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "")
    async with multiuser_db.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (email, username, display_name, role, email_verified)
            VALUES ('other-admin@example.test', 'other_admin', 'Other', 'admin', TRUE);
            """
        )
        configured_id = await conn.fetchval(
            """
            INSERT INTO users (email, username, display_name, role, email_verified)
            VALUES ('owner@example.test', 'owner', 'Owner', 'user', FALSE)
            RETURNING id;
            """
        )
        admin = await migrate_multiuser.ensure_admin(conn)
        refreshed = await conn.fetchrow("SELECT id, role, email_verified FROM users WHERE id = $1;", configured_id)

    assert admin["id"] == configured_id
    assert refreshed["role"] == "admin"
    assert refreshed["email_verified"] is True


@pytest.mark.asyncio
async def test_forced_scrape_bumps_content_version_and_flags_overlay(multiuser_db):
    async with multiuser_db.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO users (email, username, display_name, role, email_verified)
            VALUES ('reader@example.test', 'reader', 'Reader', 'user', TRUE)
            RETURNING id;
            """
        )
        novel_id = await conn.fetchval("INSERT INTO novels (title, visibility) VALUES ('Novel', 'public') RETURNING id;")
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw)
            VALUES ($1, 'epub', '/tmp/book.epub', '{}'::jsonb, 'en', FALSE)
            RETURNING id;
            """,
            novel_id,
        )
        await conn.execute(
            """
            INSERT INTO chapters (novel_id, number, source_id, title, content, content_version)
            VALUES ($1, 1, $2, 'One', 'old base', 1);
            """,
            novel_id, source_id,
        )
        await conn.execute(
            """
            INSERT INTO chapter_overlays (user_id, novel_id, chapter, content, base_version, conflict)
            VALUES ($1, $2, 1, 'my edit', 1, FALSE);
            """,
            user_id, novel_id,
        )
        source = {"id": source_id, "novel_id": novel_id, "is_raw": False, "language": "en"}
        await _persist_chapter(
            conn, source, 1.0,
            ChapterData(number=1, title="One", content="new base", url="/tmp/book.epub#1"),
            force=True,
        )
        row = await conn.fetchrow(
            """
            SELECT c.content, c.content_version, o.conflict
            FROM chapters c
            JOIN chapter_overlays o ON o.novel_id = c.novel_id AND o.chapter = c.number
            WHERE c.novel_id = $1 AND c.number = 1;
            """,
            novel_id,
        )

    assert row["content"] == "new base"
    assert row["content_version"] == 2
    assert row["conflict"] is True


@pytest.mark.asyncio
async def test_import_replace_preserves_version_and_conflicts_overlays(multiuser_db):
    async with multiuser_db.acquire() as conn:
        user_id = await conn.fetchval(
            """
            INSERT INTO users (email, username, display_name, role, email_verified)
            VALUES ('reader2@example.test', 'reader2', 'Reader', 'user', TRUE)
            RETURNING id;
            """
        )
        novel_id = await conn.fetchval("INSERT INTO novels (title, visibility) VALUES ('Novel', 'public') RETURNING id;")
        source_id = await conn.fetchval(
            """
            INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw)
            VALUES ($1, 'epub', '/tmp/old.epub', '{}'::jsonb, 'en', FALSE)
            RETURNING id;
            """,
            novel_id,
        )
        await conn.execute(
            """
            INSERT INTO chapters (novel_id, number, source_id, title, content, content_version)
            VALUES ($1, 1, $2, 'One', 'old base', 3);
            """,
            novel_id, source_id,
        )
        await conn.execute(
            """
            INSERT INTO chapter_overlays (user_id, novel_id, chapter, content, base_version, conflict)
            VALUES ($1, $2, 1, 'my edit', 3, FALSE);
            """,
            user_id, novel_id,
        )

        _novel_id, source, _offset, _cover, _invalidate = await import_commit._resolve_target(
            conn,
            {"format": "epub", "original_path": "/tmp/new.epub", "options": {"target": {"source_id": source_id}}},
            {"language": "en"},
        )
        assert source["old_versions"] == {1.0: 3}
        assert await conn.fetchval("SELECT COUNT(*) FROM chapters WHERE source_id = $1;", source_id) == 0
        assert await conn.fetchval(
            "SELECT conflict FROM chapter_overlays WHERE user_id = $1 AND novel_id = $2 AND chapter = 1;",
            user_id, novel_id,
        ) is True

        await conn.execute(
            """
            INSERT INTO chapters (novel_id, number, source_id, title, content, content_version)
            VALUES ($1, 1, $2, 'One', 'new base', 1);
            """,
            novel_id, source_id,
        )
        await conn.execute(
            "UPDATE chapter_overlays SET conflict = FALSE WHERE user_id = $1 AND novel_id = $2 AND chapter = 1;",
            user_id, novel_id,
        )
        version = await import_commit._preserve_replaced_content_version(conn, novel_id, 1.0, source)
        row = await conn.fetchrow(
            """
            SELECT c.content_version, o.conflict
            FROM chapters c
            JOIN chapter_overlays o ON o.novel_id = c.novel_id AND o.chapter = c.number
            WHERE c.novel_id = $1 AND c.number = 1;
            """,
            novel_id,
        )

    assert version == 4
    assert row["content_version"] == 4
    assert row["conflict"] is True
