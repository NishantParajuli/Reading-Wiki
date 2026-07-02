"""Safety net for the eval suite — keeps `pytest` away from the real database.

Several eval modules wipe whole tables in autouse fixtures (e.g. ``DELETE FROM
chapters CASCADE`` in ``spoiler_tests.py`` / ``pipeline_tests.py``, ``DELETE FROM
novels`` in the import tests). Those operate on whatever database the app pool is
pointed at — so running ``pytest`` against the configured (production)
``DATABASE_URL`` destroys real data. That is exactly how the live chapters once got
wiped: a routine ``pytest`` run cleaned the production novels' chapters + codex.

This conftest forces the ENTIRE eval suite onto a throwaway ``tg_pytest_*`` database
inside the configured Postgres server *before any pool is created*: it creates the
database (+ schema), repoints ``settings.DATABASE_URL`` at it, HARD-FAILS the session
if the active database is not the disposable one, then force-drops it at teardown.
The destructive fixtures can only ever touch the disposable database; the real one is
never connected to during tests.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest

import novelwiki.db.connection as db_connection
from novelwiki.config.settings import settings


def _dbname(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _with_dbname(url: str, dbname: str) -> str:
    return urlunparse(urlparse(url)._replace(path="/" + dbname))


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _dummy_db_name(base_name: str) -> str:
    safe_base = re.sub(r"[^a-zA-Z0-9_]+", "_", base_name).strip("_").lower() or "novelwiki"
    safe_base = safe_base[:24]
    suffix = f"{os.getpid()}_{uuid.uuid4().hex[:10]}"
    return f"tg_pytest_{safe_base}_{suffix}"[:63]


async def _create_test_db(test_url: str) -> None:
    """Create a disposable test database and apply the full schema to it."""
    test_name = _dbname(test_url)
    admin = await asyncpg.connect(settings.DB_SUPERUSER_URL)
    try:
        await admin.execute(f"CREATE DATABASE {_quote_ident(test_name)};")
    finally:
        await admin.close()

    # Same DDL the app applies on boot, including the conditional ANN indexes.
    from novelwiki.db.schema import DDL_QUERIES
    queries = list(DDL_QUERIES)
    if settings.EMBED_DIM <= 2000:
        queries.append("CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);")
        queries.append("CREATE INDEX IF NOT EXISTS entities_name_emb ON entities USING hnsw (name_embedding vector_cosine_ops);")
    conn = await asyncpg.connect(test_url)
    try:
        for q in queries:
            await conn.execute(q)
    finally:
        await conn.close()


async def _drop_test_db(test_name: str) -> None:
    """Remove the disposable database and any leftover connections to it."""
    try:
        try:
            await db_connection.close_db_pool()
        except Exception:
            db_connection._pool = None

        admin = await asyncpg.connect(settings.DB_SUPERUSER_URL)
        try:
            await admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = $1 AND pid <> pg_backend_pid();
                """,
                test_name,
            )
            await admin.execute(f"DROP DATABASE IF EXISTS {_quote_ident(test_name)};")
        finally:
            await admin.close()
    finally:
        db_connection._pool = None


@pytest.fixture(scope="session", autouse=True)
def _route_eval_to_test_db():
    """Redirect every eval test to a disposable database in the configured Postgres server.

    The database is created at session start, used for all DB-backed pytest work, and
    force-dropped at teardown so repeated test runs do not leave schema/data bloat in the
    local Docker Postgres container.
    """
    prod_url = settings.DATABASE_URL
    prod_name = _dbname(prod_url)
    test_name = _dummy_db_name(prod_name)
    test_url = _with_dbname(prod_url, test_name)

    try:
        asyncio.run(_create_test_db(test_url))
    except Exception:
        asyncio.run(_drop_test_db(test_name))
        raise

    # Repoint settings + drop any pool so the lazy `get_db_pool()` rebuilds on the test DB.
    settings.DATABASE_URL = test_url
    db_connection._pool = None

    # Last line of defence: never let the destructive fixtures run against the configured DB.
    active = _dbname(settings.DATABASE_URL)
    assert active == test_name and active.startswith("tg_pytest_"), (
        f"Refusing to run the eval suite against non-disposable database '{active}'. "
        "These tests wipe tables; they must only ever hit a per-run tg_pytest_* database."
    )

    try:
        yield
    finally:
        settings.DATABASE_URL = test_url
        try:
            asyncio.run(_drop_test_db(test_name))
        finally:
            settings.DATABASE_URL = prod_url
            db_connection._pool = None
