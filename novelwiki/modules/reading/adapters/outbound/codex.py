from __future__ import annotations


async def _narrative_part_chapters(connection, novel_id: int, part_label: str | None) -> list[float]:
    rows = await connection.fetch(
        """
        SELECT number FROM chapters
        WHERE novel_id=$1 AND content IS NOT NULL
          AND COALESCE(kind,'chapter')=ANY($2::text[])
          AND part_label IS NOT DISTINCT FROM $3
        ORDER BY number;
        """,
        novel_id, ["chapter", "interlude"], part_label,
    )
    return [float(row["number"]) for row in rows]


class PostgresReadingCodexTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def locked_chapter_snapshot(self, novel_id: int, chapter: float) -> dict | None:
        row = await self._connection.fetchrow(
            "SELECT title,content,COALESCE(kind,'chapter') kind,part_label FROM chapters "
            "WHERE novel_id=$1 AND number=$2 FOR UPDATE;",
            novel_id, chapter,
        )
        if not row:
            return None
        result = dict(row)
        result["narrative_part_chapters"] = await _narrative_part_chapters(
            self._connection, novel_id, row["part_label"]
        )
        return result


class PostgresReadingCodexGateway:
    def __init__(self, pool):
        self._pool = pool

    async def chapter_snapshot(self, novel_id: int, chapter: float) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT title,content,COALESCE(kind,'chapter') kind,part_label FROM chapters "
                "WHERE novel_id=$1 AND number=$2;",
                novel_id, chapter,
            )
            if not row:
                return None
            result = dict(row)
            result["narrative_part_chapters"] = await _narrative_part_chapters(
                connection, novel_id, row["part_label"]
            )
        return result

    async def chapter_numbers(
        self, novel_id: int, start: float | None = None, end: float | None = None,
        require_content: bool = False, narrative_only: bool = False,
    ) -> list[float]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT number FROM chapters WHERE novel_id=$1 "
                "AND ($2::numeric IS NULL OR number>=$2) "
                "AND ($3::numeric IS NULL OR number<=$3) "
                "AND (NOT $4 OR content IS NOT NULL) "
                "AND (NOT $5 OR COALESCE(kind,'chapter')=ANY($6::text[])) "
                "ORDER BY number;",
                novel_id, start, end, require_content, narrative_only,
                ["chapter", "interlude"],
            )
        return [float(row["number"]) for row in rows]

    async def chapter_at_or_before(
        self, novel_id: int, ceiling: float
    ) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT number,title FROM chapters WHERE novel_id=$1 AND number<=$2 "
                "ORDER BY number DESC LIMIT 1;", novel_id, ceiling,
            )
        return dict(row) if row else None
