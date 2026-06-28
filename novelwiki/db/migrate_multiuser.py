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
import json

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.passwords import hash_password
from novelwiki.auth.users import unique_username

logger = logging.getLogger(__name__)
MIGRATION_NAME = "multiuser_v1"


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


async def _is_marked(conn) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM app_migrations WHERE name = $1;", MIGRATION_NAME))


async def _mark_migrated(conn, details: dict | None = None) -> None:
    await conn.execute(
        """
        INSERT INTO app_migrations (name, details)
        VALUES ($1, $2::jsonb)
        ON CONFLICT (name) DO UPDATE SET details = EXCLUDED.details;
        """,
        MIGRATION_NAME, json.dumps(details or {}),
    )


async def _legacy_state(conn) -> dict:
    row = await conn.fetchrow(
        """
        SELECT
          EXISTS(SELECT 1 FROM novels WHERE owner_id IS NULL) AS ownerless_novels,
          EXISTS(SELECT 1 FROM reading_progress WHERE user_id IS NULL) AS progress_missing_user,
          EXISTS(SELECT 1 FROM bookmarks WHERE user_id IS NULL) AS bookmarks_missing_user,
          (SELECT COUNT(*) FROM users) AS user_count;
        """
    )
    state = dict(row)
    state["pk_legacy"] = await _pk_columns(conn, "reading_progress") == ["novel_id"]
    return state


def _needs_data_rewrite(state: dict) -> bool:
    return bool(
        state.get("ownerless_novels")
        or state.get("progress_missing_user")
        or state.get("bookmarks_missing_user")
        or state.get("pk_legacy")
    )


def _ownerless_only(state: dict) -> bool:
    return bool(
        state.get("ownerless_novels")
        and not state.get("progress_missing_user")
        and not state.get("bookmarks_missing_user")
        and not state.get("pk_legacy")
    )


async def _create_admin(conn, email: str | None = None) -> dict:
    username = await unique_username(conn, settings.ADMIN_USERNAME or "admin")
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, username, password_hash, display_name, role, email_verified)
        VALUES ($1, $2, $3, $4, 'admin', TRUE) RETURNING *;
        """,
        email or f"{username}@admin.local", username,
        hash_password(settings.ADMIN_PASSWORD), settings.ADMIN_USERNAME or "Admin",
    )
    logger.info("Bootstrapped admin user '%s' (%s).", username, email or row["email"])
    return dict(row)


async def ensure_admin(conn) -> dict | None:
    """Return the configured admin user, creating/promoting one from settings if needed."""
    email = (settings.ADMIN_EMAIL or "").lower()
    if email:
        existing = await conn.fetchrow("SELECT * FROM users WHERE email = $1;", email)
        if existing is not None:
            if existing["role"] != "admin" or not existing["email_verified"]:
                await conn.execute(
                    "UPDATE users SET role = 'admin', email_verified = TRUE WHERE id = $1;", existing["id"]
                )
                logger.info("Promoted existing user %s to admin.", email)
            return dict(await conn.fetchrow("SELECT * FROM users WHERE id = $1;", existing["id"]))

        if settings.ADMIN_PASSWORD:
            return await _create_admin(conn, email)

        return None

    admin = await conn.fetchrow("SELECT * FROM users WHERE role = 'admin' ORDER BY id LIMIT 1;")
    if admin is not None:
        return dict(admin)

    if settings.ADMIN_PASSWORD:
        return await _create_admin(conn)

    return None


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


async def maybe_migrate(allow_data_rewrite: bool | None = None) -> None:
    """Idempotent entry point for app startup: bootstrap admin + backfill legacy data.

    Data rewrites are opt-in. Normal app startup can safely mark an already-multi-user DB,
    but legacy data is reassigned only after an explicit backup confirmation.
    """
    allow_data_rewrite = (
        settings.MULTIUSER_MIGRATION_BACKUP_CONFIRMED
        if allow_data_rewrite is None
        else allow_data_rewrite
    )
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        if await _is_marked(conn):
            return

        # NB: import_jobs is intentionally excluded — new uploads may legitimately carry
        # NULL user_id during older deployments, so it must not trigger legacy migration.
        state = await _legacy_state(conn)
        if not _needs_data_rewrite(state):
            await _mark_migrated(conn, {"status": "already_multiuser", "state": state})
            return

        # Ownerless novels are valid after an admin deletes a user (FK ON DELETE SET NULL).
        # If this DB already has users and no old progress/bookmark/PK shape remains, do not
        # reinterpret those rows as single-user legacy data.
        if _ownerless_only(state) and int(state.get("user_count") or 0) > 0 and not allow_data_rewrite:
            logger.warning(
                "Ownerless novels found without a migration marker; leaving them unchanged "
                "and marking multiuser_v1 complete to avoid accidental Global promotion."
            )
            await _mark_migrated(conn, {"status": "ownerless_rows_preserved", "state": state})
            return

        if not allow_data_rewrite:
            msg = (
                "Legacy single-user data detected, but Tideglass will not rewrite paid content "
                "without an explicit backup confirmation. Take a pg_dump, test on a restored copy, "
                "then run `python -m novelwiki.db.migrate_multiuser` and type MIGRATE, or set "
                "MULTIUSER_MIGRATION_BACKUP_CONFIRMED=true for this one migration run."
            )
            logger.error(msg)
            raise RuntimeError(msg)

        admin = await ensure_admin(conn)

        if admin is None:
            msg = (
                "Legacy single-user data detected but no admin exists. Set ADMIN_PASSWORD in the "
                "environment and run `python -m novelwiki.db.migrate_multiuser` to complete migration."
            )
            logger.error(msg)
            raise RuntimeError(msg)

        async with conn.transaction():
            summary = await run_migration(conn, admin["id"])
            await _mark_migrated(conn, {"status": "migrated", "summary": summary, "state": state})
        logger.info("Multi-user migration complete (admin id=%s): %s", admin["id"], summary)


async def _cli() -> None:
    from novelwiki.db.schema import init_database

    logging.basicConfig(level=logging.INFO)
    print("⚠️  Take a backup first:  pg_dump \"$DATABASE_URL\" > backup_before_multiuser.sql")
    print(f"Target database: {settings.DATABASE_URL.rsplit('/', 1)[-1]}")
    await init_database()       # ensure the multi-user schema exists
    allow = settings.MULTIUSER_MIGRATION_BACKUP_CONFIRMED
    if not allow:
        try:
            confirm = input("Type MIGRATE after testing a backup copy, or anything else to abort: ").strip()
        except EOFError:
            confirm = ""
        allow = confirm == "MIGRATE"
        if not allow:
            print("Aborted; no data was changed.")
            return
    await maybe_migrate(allow_data_rewrite=allow)
    print("Done.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(_cli())
