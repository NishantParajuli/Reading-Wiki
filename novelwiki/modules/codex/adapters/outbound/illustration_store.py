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
                f"""WITH latest_references AS (
                    SELECT DISTINCT ON (style,character_key) id,created_at
                    FROM codex_art WHERE novel_id=$1 AND chapter<=$2 AND kind='reference'
                    ORDER BY style,character_key,chapter DESC,created_at DESC,id DESC
                ), latest_scenes AS (
                    SELECT id FROM codex_art WHERE novel_id=$1 AND chapter=$2 AND kind='scene'
                    ORDER BY created_at DESC,id DESC LIMIT 100
                )
                SELECT {fields} FROM codex_art WHERE novel_id=$1
                  AND (id IN (SELECT id FROM latest_scenes) OR id IN (
                    SELECT id FROM latest_references ORDER BY created_at DESC,id DESC LIMIT 100
                  ))
                ORDER BY created_at DESC,id DESC;""",
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
                    ORDER BY character_key,chapter DESC,created_at DESC,id DESC
                )
                SELECT * FROM latest
                ORDER BY (strpos(lower($4),lower(title))>0
                          OR strpos(lower($4),replace(replace(character_key,'-',' '),'_',' '))>0
                          OR EXISTS (
                              SELECT 1 FROM jsonb_array_elements_text(
                                  COALESCE(metadata->'aliases','[]'::jsonb)
                              ) AS alias(name)
                              WHERE length(btrim(alias.name))>0
                                AND strpos(lower($4),lower(alias.name))>0
                          )) DESC,
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

    async def context(self, novel_id, chapter, *, preceding, max_chars):
        """Prefer short Codex summaries; use bounded prose tails when none exist."""
        budget = min(9000, max(0, max_chars))
        preceding = [row for row in preceding if float(row["chapter"]) < chapter][:3]
        if not preceding or not budget:
            return {"previous_chapters": []}
        numbers = [float(row["chapter"]) for row in preceding]
        async with self.pool.acquire() as conn:
            summaries = await conn.fetch(
                "SELECT chapter,left(summary,$3) AS summary FROM chapter_summaries "
                "WHERE novel_id=$1 AND chapter=ANY($2::numeric[]);",
                novel_id,
                numbers,
                budget // len(preceding),
            )
        by_number = {float(row["chapter"]): row["summary"] for row in summaries}
        result = []
        for row in preceding:
            summary = by_number.get(float(row["chapter"]))
            text = summary or row.get("text", "")
            allowance = budget // (len(preceding) - len(result))
            text = (
                text[:allowance] if summary else text[-allowance:] if allowance else ""
            )
            result.append(
                {
                    "chapter": float(row["chapter"]),
                    "title": row.get("title", "")[:200],
                    "kind": "summary" if summary else "chapter_tail",
                    "source_hash": row.get("source_hash"),
                    "text": text,
                }
            )
            budget -= len(text)
        return {"previous_chapters": list(reversed(result))}

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

    async def range_plan(self, job_id, chapter):
        async with self.pool.acquire() as conn:
            data = await conn.fetchval(
                "SELECT plan FROM codex_art_chapter_plans WHERE job_id=$1 AND chapter=$2;",
                job_id,
                chapter,
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
