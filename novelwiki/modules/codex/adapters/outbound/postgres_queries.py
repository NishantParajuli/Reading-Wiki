from __future__ import annotations

import json

from ...public import ChapterCeiling


class PostgresCodexQueries:
    """Persistence adapter restricted to Codex-owned knowledge/cache tables."""

    def __init__(self, pool):
        self._pool = pool

    async def stats(self, novel_id: int, ceiling: ChapterCeiling) -> dict:
        async with self._pool.acquire() as connection:
            entities = await connection.fetchval(
                "SELECT COUNT(*) FROM entities "
                "WHERE first_seen_chapter <= $1 AND novel_id = $2;",
                ceiling.value, novel_id,
            )
            facts = await connection.fetchval(
                """
                SELECT COUNT(*) FROM entity_facts f
                JOIN entities e ON e.id=f.entity_id AND e.novel_id=f.novel_id
                WHERE f.chapter <= $1 AND f.novel_id=$2
                  AND e.first_seen_chapter <= $1;
                """,
                ceiling.value, novel_id,
            )
            relationships = await connection.fetchval(
                """
                SELECT COUNT(*) FROM relationships r
                JOIN entities e1 ON e1.id=r.source_id AND e1.novel_id=r.novel_id
                JOIN entities e2 ON e2.id=r.target_id AND e2.novel_id=r.novel_id
                WHERE r.chapter <= $1 AND r.novel_id=$2
                  AND e1.first_seen_chapter <= $1
                  AND e2.first_seen_chapter <= $1;
                """,
                ceiling.value, novel_id,
            )
        return {
            "entities_revealed": int(entities or 0),
            "facts_known": int(facts or 0),
            "relationships_known": int(relationships or 0),
        }

    async def list_entities(
        self, novel_id: int, ceiling: ChapterCeiling,
        entity_type: str | None, name_query: str | None,
    ) -> list[dict]:
        from .retrieval.tools import list_entities
        return await list_entities(
            novel_id, ceiling.value, entity_type=entity_type, name_query=name_query
        )

    async def resolve_entity(
        self, novel_id: int, name: str, ceiling: ChapterCeiling
    ) -> list[dict]:
        from .retrieval.tools import resolve_entity
        return await resolve_entity(novel_id, name=name, chapter_ceiling=ceiling.value)

    async def entity_profile(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> dict | None:
        from .retrieval.tools import get_entity_profile
        return await get_entity_profile(
            novel_id, entity_id=entity_id, chapter_ceiling=ceiling.value
        )

    async def relationships(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling,
        other_id: int | None = None,
    ) -> list[dict]:
        from .retrieval.tools import get_relationships
        return await get_relationships(
            novel_id, entity_id=entity_id, chapter_ceiling=ceiling.value,
            other_id=other_id,
        )

    async def timeline(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> list[dict]:
        from .retrieval.tools import get_timeline
        return await get_timeline(
            novel_id, entity_id=entity_id, chapter_ceiling=ceiling.value
        )

    async def identities(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> list[dict]:
        from .retrieval.tools import get_identity_links
        return await get_identity_links(
            novel_id, entity_id=entity_id, chapter_ceiling=ceiling.value
        )

    async def cached_profile(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> str | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT rendered_md FROM wiki_cache "
                "WHERE novel_id=$1 AND entity_id=$2 AND chapter_ceiling=$3;",
                novel_id, entity_id, ceiling.value,
            )
        return row["rendered_md"] if row else None

    async def save_profile(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling,
        rendered_md: str, model: str, evidence_ids: dict,
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO wiki_cache
                    (novel_id,entity_id,chapter_ceiling,rendered_md,model,evidence_ids)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (novel_id,entity_id,chapter_ceiling) DO UPDATE SET
                    rendered_md=EXCLUDED.rendered_md,
                    model=EXCLUDED.model,
                    evidence_ids=EXCLUDED.evidence_ids;
                """,
                novel_id, entity_id, ceiling.value, rendered_md, model,
                json.dumps(evidence_ids),
            )


class PostgresEntityMerger:
    def __init__(self, pool):
        self._pool = pool

    async def merge(self, novel_id: int, keep_id: int, drop_id: int) -> None:
        from .ingest.link import merge_entities
        async with self._pool.acquire() as connection:
            await merge_entities(novel_id, keep_id, drop_id, connection)

