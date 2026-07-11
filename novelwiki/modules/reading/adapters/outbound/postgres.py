from __future__ import annotations

from typing import Any

from ...application.dto import Bookmark, Progress


class PostgresReadingRepository:
    """The sole progress/bookmark SQL writer for the migrated Reading slice."""

    def __init__(self, connection: Any):
        self._connection = connection

    async def get_progress(self, novel_id: int, user_id: int) -> Progress:
        row = await self._connection.fetchrow(
            "SELECT last_chapter, max_chapter_read, scroll_pct FROM reading_progress "
            "WHERE novel_id = $1 AND user_id = $2;",
            novel_id,
            user_id,
        )
        if not row:
            return Progress(None, None, 0.0)
        return Progress(
            float(row["last_chapter"]) if row["last_chapter"] is not None else None,
            float(row["max_chapter_read"]) if row["max_chapter_read"] is not None else None,
            float(row["scroll_pct"] or 0),
        )

    async def chapter_exists(self, novel_id: int, chapter: float) -> bool:
        return bool(
            await self._connection.fetchval(
                "SELECT 1 FROM chapters WHERE novel_id = $1 AND number = $2;",
                novel_id,
                chapter,
            )
        )

    async def set_progress(self, novel_id: int, user_id: int, chapter: float, scroll_pct: float) -> None:
        await self._connection.execute(
            """
            INSERT INTO reading_progress (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct, updated_at)
            VALUES ($1, $2, $3, NULL, $4, now())
            ON CONFLICT (user_id, novel_id) DO UPDATE SET
                last_chapter = EXCLUDED.last_chapter,
                scroll_pct = EXCLUDED.scroll_pct,
                updated_at = now();
            """,
            user_id,
            novel_id,
            chapter,
            scroll_pct,
        )

    async def list_bookmarks(self, novel_id: int, user_id: int) -> list[Bookmark]:
        rows = await self._connection.fetch(
            "SELECT id, chapter, note, created_at FROM bookmarks "
            "WHERE novel_id = $1 AND user_id = $2 ORDER BY chapter ASC;",
            novel_id,
            user_id,
        )
        return [
            Bookmark(int(row["id"]), float(row["chapter"]), row["note"], row["created_at"])
            for row in rows
        ]

    async def add_bookmark(
        self, novel_id: int, user_id: int, chapter: float, note: str | None
    ) -> int:
        bookmark_id = await self._connection.fetchval(
            "INSERT INTO bookmarks (user_id, novel_id, chapter, note) "
            "VALUES ($1, $2, $3, $4) RETURNING id;",
            user_id,
            novel_id,
            chapter,
            note,
        )
        return int(bookmark_id)

    async def delete_bookmark(self, novel_id: int, user_id: int, bookmark_id: int) -> None:
        await self._connection.execute(
            "DELETE FROM bookmarks WHERE id = $1 AND novel_id = $2 AND user_id = $3;",
            bookmark_id,
            novel_id,
            user_id,
        )

    async def chapter_span(
        self, novel_id: int
    ) -> tuple[int, float | None, float | None]:
        row = await self._connection.fetchrow(
            "SELECT COUNT(*) AS count, MIN(number) AS min_chapter, "
            "MAX(number) AS max_chapter FROM chapters WHERE novel_id = $1;",
            novel_id,
        )
        return (
            int(row["count"] or 0),
            float(row["min_chapter"]) if row["min_chapter"] is not None else None,
            float(row["max_chapter"]) if row["max_chapter"] is not None else None,
        )

    async def trusted_ceiling(self, novel_id: int, user_id: int) -> float | None:
        value = await self._connection.fetchval(
            "SELECT max_chapter_read FROM reading_progress "
            "WHERE novel_id = $1 AND user_id = $2;",
            novel_id,
            user_id,
        )
        return float(value) if value is not None else None
