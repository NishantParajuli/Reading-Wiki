"""Chapter-scoped checkpoints inside one durable illustration range job."""

from __future__ import annotations

import json

from .illustration_store import IllustrationStore, METADATA_COLUMNS
from ...application.illustrations import IllustrationSourceChanged


class IllustrationRangeStore(IllustrationStore):
    def __init__(self, pool, chapter):
        super().__init__(pool)
        self.chapter_key = format(float(chapter), ".15g")
        self.prefix = f"chapter:{self.chapter_key}:"

    async def plan(self, job_id):
        return await self.range_plan(job_id, float(self.chapter_key))

    async def save_plan(self, job_id, plan):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                if not await conn.fetchval(
                    "SELECT 1 FROM codex_art_plans WHERE job_id=$1 FOR SHARE;",
                    job_id,
                ):
                    raise IllustrationSourceChanged(
                        "Illustration range was invalidated. Request a fresh range."
                    )
                await conn.execute(
                    """INSERT INTO codex_art_chapter_plans(job_id,chapter,plan)
                    VALUES($1,$2,$3::jsonb) ON CONFLICT(job_id,chapter) DO NOTHING;""",
                    job_id,
                    float(self.chapter_key),
                    json.dumps(plan),
                )
        winner = await self.plan(job_id)
        if winner is None:
            raise IllustrationSourceChanged(
                "Illustration range was invalidated. Request a fresh range."
            )
        return winner

    async def save(self, **values):
        return await super().save(**{**values, "slot": self.prefix + values["slot"]})

    async def for_job(self, job_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {METADATA_COLUMNS} FROM codex_art WHERE job_id=$1 AND chapter=$2 "
                "AND left(slot,length($3))=$3;",
                job_id,
                float(self.chapter_key),
                self.prefix,
            )
        return [{**dict(row), "slot": row["slot"][len(self.prefix) :]} for row in rows]
