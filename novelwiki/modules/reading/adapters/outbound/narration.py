from __future__ import annotations


class PostgresReadingNarrationGateway:
    def __init__(self, pool):
        self._pool = pool

    async def resolve_narration_text(
        self, novel_id: int, chapter: float, user_id: int | None
    ) -> dict:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT title,content,content_version,language,"
                "original_text IS NOT NULL AS has_original,kind FROM chapters "
                "WHERE novel_id=$1 AND number=$2;", novel_id, chapter,
            )
            if not row:
                return {"reason": "not_found", "text": None}
            overlay = None
            if user_id is not None:
                overlay = await connection.fetchrow(
                    "SELECT content FROM chapter_overlays WHERE user_id=$1 "
                    "AND novel_id=$2 AND chapter=$3;", user_id, novel_id, chapter,
                )
        base = {
            "title": row["title"], "language": row["language"],
            "content_version": int(row["content_version"] or 1),
            "kind": row["kind"] or "chapter", "is_overlay": False, "text": None,
        }
        if overlay and (overlay["content"] or "").strip():
            return {**base, "reason": "ok", "text": overlay["content"], "is_overlay": True}
        if row["content"] and row["content"].strip():
            return {**base, "reason": "ok", "text": row["content"]}
        return {**base, "reason": "untranslated" if row["has_original"] else "empty"}

    async def prose_chapters(
        self, novel_id: int, start: float | None = None, end: float | None = None
    ) -> list[dict]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT number,content_version FROM chapters WHERE novel_id=$1 "
                "AND (kind IS NULL OR kind='chapter') "
                "AND ($2::numeric IS NULL OR number>=$2) "
                "AND ($3::numeric IS NULL OR number<=$3) ORDER BY number;",
                novel_id, start, end,
            )
        return [
            {"number": float(row["number"]),
             "content_version": int(row["content_version"] or 1)}
            for row in rows
        ]
