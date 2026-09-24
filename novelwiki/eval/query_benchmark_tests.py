"""The endpoint performance gate must exercise authenticated SQL and clean up."""
import asyncpg
import pytest

from novelwiki.modules.identity.adapters.outbound import postgres_sessions
from novelwiki.platform.config import settings
from novelwiki.platform.database import pool as database
from tools.benchmark_queries import measure_endpoint_latency


async def _counts(connection):
    return tuple(
        [await connection.fetchval(f"SELECT COUNT(*) FROM {table}")
         for table in ("users", "sessions", "novels", "chapters")]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_session", [True, False])
async def test_endpoint_benchmark_uses_explicit_database_and_cleans_up(monkeypatch, valid_session):
    url = settings.DATABASE_URL  # eval/conftest.py supplies a per-run disposable database
    connection = await asyncpg.connect(url)
    original_pool = database._pool
    try:
        before = await _counts(connection)
        # A fallback to application configuration would fail, rather than reach
        # any other database. The benchmark must bind its explicitly supplied pool.
        monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/invalid")
        if not valid_session:
            create_session = postgres_sessions.create_session

            async def wrong_cookie(*args, **kwargs):
                await create_session(*args, **kwargs)
                return "invalid-benchmark-session"

            monkeypatch.setattr(postgres_sessions, "create_session", wrong_cookie)
            with pytest.raises(RuntimeError, match="discover expected 200, returned 401"):
                await measure_endpoint_latency(url, iterations=1)
        else:
            result = await measure_endpoint_latency(url, iterations=2)
            assert set(result) == {"health", "discover"}
            assert all(value > 0 for value in result.values())

        assert database._pool is original_pool
        assert await _counts(connection) == before
    finally:
        await connection.close()
