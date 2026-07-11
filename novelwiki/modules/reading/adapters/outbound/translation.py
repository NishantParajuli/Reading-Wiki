class PostgresReadingTranslationQuery:
    def __init__(self, pool):
        self._pool = pool

    async def count_pending(
        self, novel_id: int, from_chapter: float | None,
        to_chapter: float | None, force: bool,
    ) -> int:
        async with self._pool.acquire() as connection:
            return int(await connection.fetchval(
                """
                SELECT COUNT(*) FROM chapters
                WHERE novel_id = $1 AND original_text IS NOT NULL
                  AND ($4 OR content IS NULL)
                  AND ($2::numeric IS NULL OR number >= $2)
                  AND ($3::numeric IS NULL OR number <= $3);
                """,
                novel_id, from_chapter, to_chapter, force,
            ) or 0)
