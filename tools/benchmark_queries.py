#!/usr/bin/env python3
"""Stable query-plan budgets for critical composite reads and worker claims."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import time
from pathlib import Path
import sys
from uuid import uuid4

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUERIES = {
    "library_cards": """
        SELECT n.id FROM novels n
        LEFT JOIN library_entries le ON le.novel_id=n.id AND le.user_id=0
        LEFT JOIN reading_progress p ON p.novel_id=n.id AND p.user_id=0
        LEFT JOIN chapters c ON c.novel_id=n.id
        WHERE le.id IS NOT NULL OR n.owner_id=0 GROUP BY n.id LIMIT 60
    """,
    "work_claim": """
        SELECT id FROM jobs WHERE status='queued'
          AND (not_before IS NULL OR not_before<=NOW())
        ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
    """,
    "import_claim": """
        SELECT id FROM import_jobs WHERE status IN ('uploaded','committing')
        ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
    """,
    "narration_claim": """
        SELECT id FROM tts_jobs WHERE status='queued'
        ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
    """,
}
BASELINE = ROOT / "docs" / "architecture" / "performance-baseline.json"


async def measure(url: str) -> dict[str, float]:
    connection = await asyncpg.connect(url, timeout=5)
    try:
        result = {}
        async with connection.transaction():
            for name, query in QUERIES.items():
                plan = await connection.fetchval(
                    "EXPLAIN (FORMAT JSON) " + query
                )
                parsed = json.loads(plan) if isinstance(plan, str) else plan
                result[name] = float(parsed[0]["Plan"]["Total Cost"])
        return result
    finally:
        await connection.close()


async def measure_worker_claim_throughput(
    url: str, iterations: int = 100
) -> float:
    """Exercise real locked claim/update work and roll the disposable fixture back."""
    connection = await asyncpg.connect(url, timeout=5)
    try:
        transaction = connection.transaction()
        await transaction.start()
        await connection.executemany(
            "INSERT INTO jobs (kind,status,options) VALUES ('scrape','queued','{}')",
            [() for _ in range(iterations)],
        )
        started = time.perf_counter()
        for _ in range(iterations):
            row = await connection.fetchrow(
                """
                WITH candidate AS (
                  SELECT id FROM jobs WHERE status='queued'
                  ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE jobs SET status='running',claimed_at=now()
                WHERE id=(SELECT id FROM candidate) RETURNING id
                """
            )
            if row is None:
                raise RuntimeError("worker throughput fixture exhausted early")
        elapsed = time.perf_counter() - started
        await transaction.rollback()
        return iterations / max(elapsed, 0.000001)
    finally:
        await connection.close()


@asynccontextmanager
async def _endpoint_fixture(url: str):
    """Bind the standalone benchmark to its explicit database, without app workers."""
    from novelwiki.modules.identity.adapters.outbound.postgres_sessions import create_session
    from novelwiki.platform.database import pool as database

    pool = await asyncpg.create_pool(url, min_size=1, max_size=3, timeout=5)
    previous_pool = database._pool
    database._pool = pool
    user_id = novel_id = None
    title = f"Benchmark discovery {uuid4().hex}"
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                user_id = await connection.fetchval(
                    "INSERT INTO users (email,username,email_verified) "
                    "VALUES ($1,$2,TRUE) RETURNING id",
                    f"{uuid4().hex}@benchmark.invalid", f"bench_{uuid4().hex[:20]}",
                )
                token = await create_session(connection, user_id, "query benchmark")
                novel_id = await connection.fetchval(
                    "INSERT INTO novels (title,visibility) VALUES ($1,'global') RETURNING id",
                    title,
                )
                await connection.execute(
                    "INSERT INTO chapters (novel_id,number,title,content,translation_status) "
                    "VALUES ($1,1,'Benchmark chapter','Synthetic benchmark passage.','done')",
                    novel_id,
                )
        yield token, novel_id, title
    finally:
        try:
            async with pool.acquire() as connection:
                async with connection.transaction():
                    if novel_id is not None:
                        await connection.execute("DELETE FROM novels WHERE id=$1", novel_id)
                    if user_id is not None:
                        await connection.execute("DELETE FROM users WHERE id=$1", user_id)
        finally:
            database._pool = previous_pool
            await pool.close()


def _validate_endpoint_response(response, name: str, novel_id: int, title: str) -> None:
    if response.status_code != 200:
        raise RuntimeError(
            f"endpoint benchmark {name} expected 200, returned {response.status_code}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"endpoint benchmark {name} returned invalid JSON") from exc
    if name == "health":
        valid = isinstance(data, dict) and data.get("status") == "healthy"
    else:
        valid = (
            isinstance(data, dict)
            and type(data.get("total")) is int and data["total"] == 1
            and data.get("offset") == 0 and data.get("limit") == 1
            and isinstance(data.get("items"), list) and len(data["items"]) == 1
            and isinstance(data["items"][0], dict)
            and data["items"][0].get("id") == novel_id
            and data["items"][0].get("title") == title
            and data["items"][0].get("chapter_count") == 1
        )
    if not valid:
        raise RuntimeError(f"endpoint benchmark {name} returned unexpected response data")


async def measure_endpoint_latency(url: str, iterations: int = 12) -> dict[str, float]:
    """Measure successful health and authenticated, populated Discover ASGI requests."""
    import httpx
    from novelwiki.api.app import app
    from novelwiki.platform.config import settings

    if iterations < 1:
        raise ValueError("endpoint benchmark iterations must be positive")
    result = {}
    async with _endpoint_fixture(url) as (token, novel_id, title):
        # ASGITransport deliberately does not run the application's lifespan:
        # this scoped pool is all these read paths need; no workers/providers start.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://benchmark",
            cookies={settings.SESSION_COOKIE: token},
        ) as client:
            for name, path in {"health": "/health", "discover": "/api/discover"}.items():
                samples = []
                params = {"q": title, "limit": 1} if name == "discover" else None
                for _ in range(iterations):
                    started = time.perf_counter()
                    response = await client.get(path, params=params)
                    samples.append((time.perf_counter() - started) * 1000)
                    _validate_endpoint_response(response, name, novel_id, title)
                samples.sort()
                index = min(len(samples) - 1, int(len(samples) * 0.95))
                result[name] = samples[index]
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    measured = await measure(args.database_url)
    endpoint_latency = await measure_endpoint_latency(args.database_url)
    claim_throughput = await measure_worker_claim_throughput(args.database_url)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures = []
    for name, cost in measured.items():
        budget = float(baseline["queries"][name]["max_total_cost"])
        print(f"{name}: total_cost={cost:.2f}, budget={budget:.2f}")
        if args.check and cost > budget:
            failures.append(f"{name}: {cost:.2f} > {budget:.2f}")
    for name, latency in endpoint_latency.items():
        budget = float(baseline["endpoints"][name]["max_p95_ms"])
        print(f"{name}: p95_ms={latency:.2f}, budget={budget:.2f}")
        if args.check and latency > budget:
            failures.append(f"{name}: {latency:.2f}ms > {budget:.2f}ms")
    minimum = float(baseline["worker_claim"]["min_claims_per_second"])
    print(
        f"worker_claim: claims_per_second={claim_throughput:.2f}, "
        f"minimum={minimum:.2f}"
    )
    if args.check and claim_throughput < minimum:
        failures.append(
            f"worker_claim: {claim_throughput:.2f}/s < {minimum:.2f}/s"
        )
    if failures:
        print("performance budget exceeded: " + "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
