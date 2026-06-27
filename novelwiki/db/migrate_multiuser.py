"""One-time, idempotent migration from the single-user app to multi-user.

What it does (only ever touches *legacy* data — rows with no owner):
  1. Bootstrap an admin user from ADMIN_EMAIL / ADMIN_PASSWORD (or promote an existing
     account with that email). Skipped if an admin already exists.
  2. Reassign every pre-existing novel to the admin as a **global** novel.
  3. Backfill user_id on reading_progress / bookmarks / import_jobs to the admin, and
     swap reading_progress's primary key from (novel_id) to (user_id, novel_id).
  4. Seed the admin's library_entries from each novel's legacy shelf/status_tags.

It is safe to run repeatedly: each step is guarded so already-migrated rows are left
alone. It is called automatically at startup (see api/app.py) and can also be run as a
CLI for an explicit, supervised migration:

    python -m novelwiki.db.migrate_multiuser

⚠️ This rewrites data you paid real money to produce. TAKE A BACKUP FIRST:
    pg_dump "$DATABASE_URL" > backup_before_multiuser.sql
Test against a restored copy before running on production.
"""
import logging

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.passwords import hash_password
from novelwiki.auth.users import unique_username

logger = logging.getLogger(__name__)


async def _pk_columns(conn, table: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = $1::regclass AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum);
        """,
        table,
    )
    return [r["attname"] for r in rows]


async def ensure_admin(conn) -> dict | None:
    """Return the admin user, creating/promoting one from settings if needed (idempotent)."""
    admin = await conn.fetchrow("SELECT * FROM users WHERE role = 'admin' ORDER BY id LIMIT 1;")
    if admin is not None:
        return dict(admin)

    email = (settings.ADMIN_EMAIL or "").lower()
    if email:
        existing = await conn.fetchrow("SELECT * FROM users WHERE email = $1;", email)
        if existing is not None:
            await conn.execute(
                "UPDATE users SET role = 'admin', email_verified = TRUE WHERE id = $1;", existing["id"]
            )
            logger.info("Promoted existing user %s to admin.", email)
            return dict(await conn.fetchrow("SELECT * FROM users WHERE id = $1;", existing["id"]))

    if not settings.ADMIN_PASSWORD:
        return None

    username = await unique_username(conn, settings.ADMIN_USERNAME or "admin")
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, username, password_hash, display_name, role, email_verified)
        VALUES ($1, $2, $3, $4, 'admin', TRUE) RETURNING *;
        """,
        email or f"{username}@admin.local", username,
        hash_password(settings.ADMIN_PASSWORD), settings.ADMIN_USERNAME or "Admin",
    )
    logger.info("Bootstrapped admin user '%s' (%s).", username, email)
    return dict(row)


async def run_migration(conn, admin_id: int) -> dict:
    """Reassign legacy data to the admin. Must be called inside a transaction."""
    summary: dict[str, int] = {}

    summary["novels_to_global"] = int(
        (await conn.execute(
            "UPDATE novels SET owner_id = $1, visibility = 'global' WHERE owner_id IS NULL;",
            admin_id,
        )).split()[-1]
    )

    # reading_progress: backfill user_id, then move PK to (user_id, novel_id).
    summary["progress_backfilled"] = int(
        (await conn.execute(
            "UPDATE reading_progress SET user_id = $1 WHERE user_id IS NULL;", admin_id
        )).split()[-1]
    )
    if await _pk_columns(conn, "reading_progress") != ["user_id", "novel_id"]:
        await conn.execute("ALTER TABLE reading_progress ALTER COLUMN user_id SET NOT NULL;")
        await conn.execute("ALTER TABLE reading_progress DROP CONSTRAINT IF EXISTS reading_progress_pkey;")
        await conn.execute("ALTER TABLE reading_progress ADD PRIMARY KEY (user_id, novel_id);")
        summary["progress_pk_swapped"] = 1

    summary["bookmarks_backfilled"] = int(
        (await conn.execute(
            "UPDATE bookmarks SET user_id = $1 WHERE user_id IS NULL;", admin_id
        )).split()[-1]
    )
    summary["import_jobs_backfilled"] = int(
        (await conn.execute(
            "UPDATE import_jobs SET user_id = $1 WHERE user_id IS NULL;", admin_id
        )).split()[-1]
    )

    # Seed admin's library from each novel's legacy shelf/tags (global novels included).
    summary["library_seeded"] = int(
        (await conn.execute(
            """
            INSERT INTO library_entries (user_id, novel_id, shelf, status_tags)
            SELECT $1, id, shelf, COALESCE(status_tags, '{}') FROM novels
            ON CONFLICT (user_id, novel_id) DO NOTHING;
            """,
            admin_id,
        )).split()[-1]
    )
    return summary


async def maybe_migrate() -> None:
    """Idempotent entry point for app startup: bootstrap admin + backfill legacy data."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        admin = await ensure_admin(conn)
        # NB: import_jobs is intentionally excluded — new uploads legitimately carry a NULL
        # user_id until Phase 1 wires upload ownership, so it must not re-trigger migration.
        legacy = await conn.fetchval(
            """
            SELECT EXISTS(SELECT 1 FROM novels WHERE owner_id IS NULL)
                OR EXISTS(SELECT 1 FROM reading_progress WHERE user_id IS NULL)
                OR EXISTS(SELECT 1 FROM bookmarks WHERE user_id IS NULL);
            """
        )
        pk_legacy = await _pk_columns(conn, "reading_progress") == ["novel_id"]
        if not legacy and not pk_legacy:
            return  # already multi-user

        if admin is None:
            logger.warning(
                "Legacy single-user data detected but no admin exists. Set ADMIN_PASSWORD in the "
                "environment and run `python -m novelwiki.db.migrate_multiuser` to complete migration."
            )
            return

        async with conn.transaction():
            summary = await run_migration(conn, admin["id"])
        logger.info("Multi-user migration complete (admin id=%s): %s", admin["id"], summary)


async def _cli() -> None:
    from novelwiki.db.schema import init_database

    logging.basicConfig(level=logging.INFO)
    print("⚠️  Take a backup first:  pg_dump \"$DATABASE_URL\" > backup_before_multiuser.sql")
    print(f"Target database: {settings.DATABASE_URL.rsplit('/', 1)[-1]}")
    await init_database()       # ensure the multi-user schema exists
    await maybe_migrate()
    print("Done.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_cli())
