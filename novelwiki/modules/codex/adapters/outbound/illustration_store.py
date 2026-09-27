from __future__ import annotations
import json
import uuid

from novelwiki.modules.codex.application.illustrations import IllustrationSourceChanged

METADATA_COLUMNS = "id,novel_id,chapter,kind,character_key,title,caption,style,source_hash,metadata,created_at,job_id,slot"


class IllustrationStore:
    def __init__(self, pool):
        self.pool = pool

    async def list(self, novel_id: int, chapter: float, *, images=False):
        fields = "*" if images else METADATA_COLUMNS
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {fields} FROM codex_art WHERE novel_id=$1 AND chapter<=$2 "
                "AND (kind='reference' OR chapter=$2) ORDER BY created_at DESC LIMIT 100;",
                novel_id,
                chapter,
            )
        return [dict(row) for row in rows]

    async def references(self, novel_id: int, chapter: float, style: str, content: str):
        """Keep old recurring identities available without sending revision history."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""WITH latest AS (
                    SELECT DISTINCT ON (character_key) {METADATA_COLUMNS}
                    FROM codex_art
                    WHERE novel_id=$1 AND chapter<=$2 AND style=$3
                      AND kind='reference' AND character_key IS NOT NULL
                    ORDER BY character_key,created_at DESC,id DESC
                )
                SELECT * FROM latest
                ORDER BY (strpos(lower($4),lower(title))>0
                          OR strpos(lower($4),replace(replace(character_key,'-',' '),'_',' '))>0) DESC,
                         created_at DESC,id DESC
                LIMIT 100;""",
                novel_id,
                chapter,
                style,
                content,
            )
        return [dict(row) for row in rows]

    async def get(self, novel_id: int, art_id: uuid.UUID, *, images=True):
        fields = "*" if images else METADATA_COLUMNS
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {fields} FROM codex_art WHERE novel_id=$1 AND id=$2;",
                novel_id,
                uuid.UUID(str(art_id)),
            )
        return dict(row) if row else None

    async def save(
        self,
        *,
        novel_id,
        chapter,
        kind,
        key,
        title,
        caption,
        style,
        source_hash,
        metadata,
        image,
        job_id,
        slot,
    ):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # A chapter edit/reset deletes plans before clearing derived images.
                # Lock the plan so an in-flight render cannot recreate invalidated art.
                if not await conn.fetchval(
                    "SELECT 1 FROM codex_art_plans WHERE job_id=$1 FOR SHARE;",
                    job_id,
                ):
                    raise IllustrationSourceChanged(
                        "Illustration context was invalidated. Request a fresh set."
                    )
                row = await conn.fetchrow(
                    """INSERT INTO codex_art(id,novel_id,chapter,kind,character_key,title,caption,style,
                           source_hash,metadata,image,job_id,slot)
                       VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13)
                       ON CONFLICT(job_id,slot) DO UPDATE SET job_id=EXCLUDED.job_id RETURNING *;""",
                    uuid.uuid4(),
                    novel_id,
                    chapter,
                    kind,
                    key,
                    title,
                    caption,
                    style,
                    source_hash,
                    json.dumps(metadata),
                    image,
                    job_id,
                    slot,
                )
        return dict(row)

    async def context(self, novel_id, chapter):
        async with self.pool.acquire() as conn:
            summaries = await conn.fetch(
                "SELECT chapter,summary FROM chapter_summaries WHERE novel_id=$1 AND chapter<$2 ORDER BY chapter DESC LIMIT 8;",
                novel_id,
                chapter,
            )
            facts = await conn.fetch(
                """SELECT e.canonical_name,f.content FROM entity_facts f
                JOIN entities e ON e.id=f.entity_id AND e.novel_id=f.novel_id
                WHERE f.novel_id=$1 AND f.chapter<=$2 AND e.first_seen_chapter<=$2
                AND e.type='character' ORDER BY f.chapter DESC,f.id DESC LIMIT 120;""",
                novel_id,
                chapter,
            )
        return {
            "recent_summaries": [dict(r) for r in summaries],
            "character_facts": [dict(r) for r in facts],
        }

    async def for_job(self, job_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id,novel_id,chapter,kind,character_key,title,caption,style,source_hash,metadata,slot FROM codex_art WHERE job_id=$1;",
                job_id,
            )
        return [dict(row) for row in rows]

    async def plan(self, job_id):
        async with self.pool.acquire() as conn:
            data = await conn.fetchval(
                "SELECT plan FROM codex_art_plans WHERE job_id=$1;", job_id
            )
        return json.loads(data) if isinstance(data, str) else data

    async def save_plan(self, job_id, plan):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO codex_art_plans(job_id,plan) VALUES($1,$2::jsonb) ON CONFLICT(job_id) DO NOTHING;",
                job_id,
                json.dumps(plan),
            )
        return await self.plan(job_id)
