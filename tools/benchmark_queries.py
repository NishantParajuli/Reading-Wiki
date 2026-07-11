#!/usr/bin/env python3
"""Stable query-plan budgets for critical composite reads and worker claims."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import asyncpg

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
BASELINE = Path(__file__).resolve().parents[1] / "docs" / "architecture" / "performance-baseline.json"


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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    measured = await measure(args.database_url)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures = []
    for name, cost in measured.items():
        budget = float(baseline["queries"][name]["max_total_cost"])
        print(f"{name}: total_cost={cost:.2f}, budget={budget:.2f}")
        if args.check and cost > budget:
            failures.append(f"{name}: {cost:.2f} > {budget:.2f}")
    if failures:
        print("performance budget exceeded: " + "; ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
