"""Safety net for the eval suite — keeps `pytest` away from the real database.

Several eval modules wipe whole tables in autouse fixtures (e.g. ``DELETE FROM
chapters CASCADE`` in ``spoiler_tests.py`` / ``pipeline_tests.py``, ``DELETE FROM
novels`` in the import tests). Those operate on whatever database the app pool is
pointed at — so running ``pytest`` against the configured (production)
``DATABASE_URL`` destroys real data. That is exactly how the live chapters once got
wiped: a routine ``pytest`` run cleaned the production novels' chapters + codex.

This conftest forces the ENTIRE eval suite onto a throwaway ``<db>_test`` database
*before any pool is created*: it derives the test DB name, creates it (+ schema) if
missing, repoints ``settings.DATABASE_URL`` at it, and then HARD-FAILS the session
if the active database isn't a ``*_test`` one. The destructive fixtures can only
ever touch the disposable database; the real one is never connected to during tests.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest

import novelwiki.db.connection as db_connection
from novelwiki.config.settings import settings


def _dbname(url: str) -> str:
    return urlparse(url).path.lstrip("/")


def _with_dbname(url: str, dbname: str) -> str:
    return urlunparse(urlparse(url)._replace(path="/" + dbname))


async def _ensure_test_db(test_url: str) -> None:
    """Create the test database (if absent) and apply the full schema to it."""
    test_name = _dbname(test_url)
    admin = await asyncpg.connect(settings.DB_SUPERUSER_URL)
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1;", test_name)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{test_name}";')
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


@pytest.fixture(scope="session", autouse=True)
def _route_eval_to_test_db():
    """Redirect every eval test to a disposable ``*_test`` database. Runs once, before
    any test (and therefore before any destructive autouse fixture) touches a pool."""
    prod_url = settings.DATABASE_URL
    prod_name = _dbname(prod_url)
    test_name = prod_name if prod_name.endswith("_test") else f"{prod_name}_test"
    test_url = _with_dbname(prod_url, test_name)

    asyncio.run(_ensure_test_db(test_url))

    # Repoint settings + drop any pool so the lazy `get_db_pool()` rebuilds on the test DB.
    settings.DATABASE_URL = test_url
    db_connection._pool = None

    # Last line of defence: never let the destructive fixtures run against a non-test DB.
    active = _dbname(settings.DATABASE_URL)
    assert active.endswith("_test"), (
        f"Refusing to run the eval suite against non-test database '{active}'. "
        "These tests wipe tables; they must only ever hit a *_test database."
    )

    yield

    settings.DATABASE_URL = prod_url
    db_connection._pool = None
