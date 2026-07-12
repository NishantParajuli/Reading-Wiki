#!/usr/bin/env python3
"""Stable query-plan budgets for critical composite reads and worker claims."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
import sys

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
    connection = await asyncpg.connect(url)
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
    connection = await asyncpg.connect(url)
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


async def measure_endpoint_latency(iterations: int = 12) -> dict[str, float]:
    """Measure complete ASGI request paths, including dependencies and serialization."""
    import httpx
    from novelwiki.api.app import app

    result = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://benchmark"
    ) as client:
        for name, path in {"health": "/health", "discover": "/api/discover"}.items():
            samples = []
            for _ in range(iterations):
                started = time.perf_counter()
                response = await client.get(path)
                samples.append((time.perf_counter() - started) * 1000)
                if response.status_code >= 500:
                    raise RuntimeError(
                        f"endpoint benchmark {path} returned {response.status_code}"
                    )
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
    endpoint_latency = await measure_endpoint_latency()
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
