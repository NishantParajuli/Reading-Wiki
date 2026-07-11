from __future__ import annotations


class PostgresCodexTransactionService:
    """Codex-owned artifact checks used by atomic cross-module workflows."""

    def __init__(self, connection):
        self._connection = connection

    async def has_chapter_artifacts(
        self, novel_id: int, chapters: tuple[float, ...]
    ) -> bool:
        if not chapters:
            return False
        return bool(await self._connection.fetchval(
            """
            SELECT
                EXISTS (SELECT 1 FROM chunks WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM entities WHERE novel_id=$1 AND first_seen_chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM entity_descriptions WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM entity_aliases WHERE novel_id=$1 AND revealed_at_chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM identity_links WHERE novel_id=$1 AND revealed_at_chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM entity_facts WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM relationships WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM events WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM extraction_state WHERE novel_id=$1 AND chapter=ANY($2::numeric[]));
            """,
            novel_id, list(chapters),
        ))

    async def invalidate_chapter_range(
        self, novel_id: int, start: float, end: float
    ) -> None:
        for table in (
            "extraction_state", "entity_facts", "relationships", "events",
            "entity_descriptions",
        ):
            await self._connection.execute(
                f"DELETE FROM {table} WHERE novel_id=$1 AND chapter BETWEEN $2 AND $3;",
                novel_id, start, end,
            )
        await self._connection.execute("DELETE FROM wiki_cache WHERE novel_id=$1;", novel_id)
        await self._connection.execute("DELETE FROM query_cache WHERE novel_id=$1;", novel_id)
