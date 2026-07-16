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
             OR EXISTS (SELECT 1 FROM chapter_summaries WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM entity_activity WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM entity_state_transitions WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM relationship_state_transitions WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM plot_thread_updates WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM extraction_contexts WHERE novel_id=$1 AND chapter=ANY($2::numeric[]))
             OR EXISTS (SELECT 1 FROM memory_segments m WHERE m.novel_id=$1 AND EXISTS (
                  SELECT 1 FROM unnest($2::numeric[]) AS supplied(chapter_number)
                  WHERE supplied.chapter_number BETWEEN m.start_chapter AND m.through_chapter
             ))
             OR EXISTS (SELECT 1 FROM extraction_state WHERE novel_id=$1 AND chapter=ANY($2::numeric[]));
            """,
            novel_id, list(chapters),
        ))

    async def invalidate_chapter_range(
        self, novel_id: int, start: float, end: float
    ) -> None:
        for table in (
            "entity_facts", "relationships", "events", "entity_descriptions",
        ):
            await self._connection.execute(
                f"DELETE FROM {table} WHERE novel_id=$1 AND chapter BETWEEN $2 AND $3;",
                novel_id, start, end,
            )
        await self._connection.execute(
            "UPDATE entities SET description=NULL WHERE novel_id=$1 "
            "AND first_seen_chapter BETWEEN $2 AND $3;",
            novel_id, start, end,
        )
        await self._connection.execute(
            "DELETE FROM identity_links WHERE novel_id=$1 AND revealed_at_chapter BETWEEN $2 AND $3;",
            novel_id, start, end,
        )
        await self._connection.execute(
            "DELETE FROM entity_aliases WHERE novel_id=$1 AND revealed_at_chapter BETWEEN $2 AND $3 "
            "AND revealed_at_chapter<>0;",
            novel_id, start, end,
        )
        # Context, summaries and temporal state are prefix-derived; invalidate
        # the entire suffix so no stale current-state view remains readable.
        for table in (
            "extraction_state", "chapter_summaries", "entity_activity",
            "entity_state_transitions", "relationship_state_transitions",
            "plot_thread_updates", "extraction_contexts",
        ):
            await self._connection.execute(
                f"DELETE FROM {table} WHERE novel_id=$1 AND chapter >= $2;",
                novel_id, start,
            )
        await self._connection.execute(
            "DELETE FROM memory_segments WHERE novel_id=$1 AND through_chapter >= $2;",
            novel_id, start,
        )
        await self._connection.execute(
            "DELETE FROM plot_threads t WHERE t.novel_id=$1 AND t.introduced_at_chapter >= $2 "
            "AND NOT EXISTS (SELECT 1 FROM plot_thread_updates u WHERE u.thread_id=t.id);",
            novel_id, start,
        )
        await self._connection.execute("DELETE FROM wiki_cache WHERE novel_id=$1;", novel_id)
        await self._connection.execute("DELETE FROM query_cache WHERE novel_id=$1;", novel_id)
