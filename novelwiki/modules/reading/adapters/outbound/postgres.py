from __future__ import annotations

from typing import Any

from novelwiki.kernel.errors import NotFound

from ...application.dto import (
    Bookmark,
    ChapterListItem,
    ChapterSnapshot,
    Contribution,
    Progress,
)


class PostgresReadingRepository:
    """The sole progress/bookmark SQL writer for the migrated Reading slice."""

    def __init__(self, connection: Any):
        self._connection = connection

    async def source_chapter_numbers(self, source_id: int) -> tuple[float, ...]:
        rows = await self._connection.fetch(
            "SELECT number FROM chapters WHERE source_id = $1 ORDER BY number;", source_id
        )
        return tuple(float(row["number"]) for row in rows)

    async def renumber_source_chapters(
        self, source_id: int, novel_id: int, delta: float
    ) -> int:
        if delta == 0:
            return 0
        await self._connection.execute(
            """
            UPDATE bookmarks SET chapter = chapter + $2
            WHERE novel_id = $3
              AND chapter IN (SELECT number FROM chapters WHERE source_id = $1);
            """,
            source_id, delta, novel_id,
        )
        await self._connection.execute(
            """
            UPDATE reading_progress SET
                last_chapter = CASE
                    WHEN last_chapter IN (SELECT number FROM chapters WHERE source_id = $1)
                    THEN last_chapter + $2 ELSE last_chapter END,
                max_chapter_read = CASE
                    WHEN max_chapter_read IN (SELECT number FROM chapters WHERE source_id = $1)
                    THEN max_chapter_read + $2 ELSE max_chapter_read END
            WHERE novel_id = $3;
            """,
            source_id, delta, novel_id,
        )
        await self._connection.execute(
            "UPDATE chapters SET number = number + $2 + 1000000 WHERE source_id = $1;",
            source_id, delta,
        )
        status = await self._connection.execute(
            "UPDATE chapters SET number = number - 1000000 WHERE source_id = $1;",
            source_id,
        )
        try:
            return int(status.split()[-1])
        except (ValueError, IndexError):
            return 0

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

    async def list_chapters(self, novel_id: int) -> list[ChapterListItem]:
        rows = await self._connection.fetch(
            """
            SELECT number, title, language, is_translated, translation_status,
                   (content IS NOT NULL OR raw_html IS NOT NULL) AS has_content,
                   word_count, kind, part_label
            FROM chapters WHERE novel_id = $1 ORDER BY number ASC;
            """,
            novel_id,
        )
        return [
            ChapterListItem(
                number=float(row["number"]), title=row["title"],
                language=row["language"], is_translated=bool(row["is_translated"]),
                translation_status=row["translation_status"],
                has_content=bool(row["has_content"]),
                word_count=row["word_count"], kind=row["kind"] or "chapter",
                part_label=row["part_label"],
            )
            for row in rows
        ]

    async def get_chapter(
        self, novel_id: int, number: float, user_id: int | None
    ) -> ChapterSnapshot:
        row = await self._connection.fetchrow(
            """
            SELECT c.number, c.title, c.content, c.raw_html, c.content_version, c.word_count,
                   (c.original_text IS NOT NULL) AS has_original,
                   c.language, c.is_translated, c.translation_status, c.source_id
            FROM chapters c
            WHERE c.novel_id = $1 AND c.number = $2;
            """,
            novel_id, number,
        )
        if row is None:
            raise NotFound("Chapter not found.")
        previous = await self._connection.fetchrow(
            "SELECT number, title FROM chapters WHERE novel_id = $1 AND number < $2 "
            "ORDER BY number DESC LIMIT 1;",
            novel_id, number,
        )
        following = await self._connection.fetchrow(
            "SELECT number, title, (content IS NULL AND original_text IS NOT NULL) AS is_raw "
            "FROM chapters WHERE novel_id = $1 AND number > $2 "
            "ORDER BY number ASC LIMIT 1;",
            novel_id, number,
        )
        overlay = None
        if user_id is not None:
            overlay = await self._connection.fetchrow(
                "SELECT content, base_version, origin, conflict FROM chapter_overlays "
                "WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
                user_id, novel_id, number,
            )
            await self._connection.execute(
                """
                INSERT INTO reading_progress
                    (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct, updated_at)
                VALUES ($1, $2, $3, $3, 0, now())
                ON CONFLICT (user_id, novel_id) DO UPDATE SET
                    last_chapter = COALESCE(reading_progress.last_chapter, EXCLUDED.last_chapter),
                    max_chapter_read = GREATEST(
                        COALESCE(reading_progress.max_chapter_read, EXCLUDED.max_chapter_read),
                        EXCLUDED.max_chapter_read
                    ),
                    scroll_pct = COALESCE(reading_progress.scroll_pct, EXCLUDED.scroll_pct),
                    updated_at = now();
                """,
                user_id, novel_id, number,
            )
        base_version = int(row["content_version"] or 1)
        overlay_version = int(overlay["base_version"]) if overlay else None
        return ChapterSnapshot(
            number=float(row["number"]), title=row["title"], content=row["content"],
            raw_html=row["raw_html"], content_version=base_version,
            word_count=int(row["word_count"]) if row["word_count"] is not None else None,
            has_original=bool(row["has_original"]), language=row["language"],
            is_translated=bool(row["is_translated"]),
            translation_status=row["translation_status"],
            source_id=int(row["source_id"]) if row["source_id"] is not None else None,
            adapter=None, source_is_raw=False,
            previous_number=float(previous["number"]) if previous else None,
            previous_title=previous["title"] if previous else None,
            next_number=float(following["number"]) if following else None,
            next_title=following["title"] if following else None,
            next_is_raw=bool(following["is_raw"]) if following else False,
            overlay_content=overlay["content"] if overlay else None,
            overlay_base_version=overlay_version,
            overlay_origin=overlay["origin"] if overlay else None,
            overlay_conflict=bool(
                overlay and (overlay["conflict"] or overlay_version < base_version)
            ),
        )

    async def chapter_version_and_source(
        self, novel_id: int, number: float
    ) -> tuple[int, bool]:
        row = await self._connection.fetchrow(
            "SELECT content_version, original_text IS NOT NULL AS has_source "
            "FROM chapters WHERE novel_id = $1 AND number = $2;",
            novel_id, number,
        )
        if row is None:
            raise NotFound("Chapter not found.")
        return int(row["content_version"] or 1), bool(row["has_source"])

    async def update_base_content(
        self, novel_id: int, number: float, content: str,
        keep_overlay_user: int | None = None,
    ) -> int:
        new_version = await self._connection.fetchval(
            """
            UPDATE chapters
            SET content = $3, is_translated = TRUE, translation_status = 'done',
                content_version = content_version + 1
            WHERE novel_id = $1 AND number = $2 RETURNING content_version;
            """,
            novel_id, number, content,
        )
        if new_version is None:
            raise NotFound("Chapter not found.")
        await self._connection.execute(
            "UPDATE chapter_overlays SET conflict = TRUE, updated_at = now() "
            "WHERE novel_id = $1 AND chapter = $2 AND base_version < $3 "
            "AND ($4::bigint IS NULL OR user_id <> $4);",
            novel_id, number, new_version, keep_overlay_user,
        )
        if keep_overlay_user is not None:
            await self._connection.execute(
                "UPDATE chapter_overlays SET base_version = $3, conflict = FALSE, "
                "updated_at = now() WHERE novel_id = $1 AND chapter = $2 AND user_id = $4;",
                novel_id, number, new_version, keep_overlay_user,
            )
        return int(new_version)

    async def save_overlay(
        self, novel_id: int, number: float, user_id: int, content: str,
        base_version: int, origin: str,
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO chapter_overlays
                (user_id, novel_id, chapter, content, base_version, origin, conflict)
            VALUES ($1, $2, $3, $4, $5, $6, FALSE)
            ON CONFLICT (user_id, novel_id, chapter) DO UPDATE SET
                content = EXCLUDED.content, base_version = EXCLUDED.base_version,
                origin = EXCLUDED.origin, conflict = FALSE, updated_at = now();
            """,
            user_id, novel_id, number, content, base_version, origin,
        )

    async def delete_overlay(
        self, novel_id: int, number: float, user_id: int
    ) -> None:
        await self._connection.execute(
            "DELETE FROM chapter_overlays WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
            user_id, novel_id, number,
        )

    async def reanchor_overlay(
        self, novel_id: int, number: float, user_id: int, base_version: int
    ) -> None:
        await self._connection.execute(
            "UPDATE chapter_overlays SET base_version = $4, conflict = FALSE, updated_at = now() "
            "WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
            user_id, novel_id, number, base_version,
        )

    async def get_overlay(
        self, novel_id: int, number: float, user_id: int
    ) -> tuple[str, int] | None:
        row = await self._connection.fetchrow(
            "SELECT content, base_version FROM chapter_overlays "
            "WHERE user_id = $1 AND novel_id = $2 AND chapter = $3;",
            user_id, novel_id, number,
        )
        if row is None:
            return None
        return str(row["content"]), int(row["base_version"])

    async def create_contribution(
        self, novel_id: int, number: float, user_id: int, content: str,
        base_version: int, status: str, auto_merged: bool,
    ) -> int:
        return int(await self._connection.fetchval(
            """
            INSERT INTO contributions
                (novel_id, from_user_id, chapter, content, base_version, status, reviewed_at)
            VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $7 THEN now() ELSE NULL END)
            RETURNING id;
            """,
            novel_id, user_id, number, content, base_version, status, auto_merged,
        ))

    async def list_contributions(
        self, novel_id: int, status: str
    ) -> list[Contribution]:
        rows = await self._connection.fetch(
            """
            SELECT k.id, k.chapter, k.content, k.base_version, k.status, k.created_at,
                   k.from_user_id, c.content AS base_content, c.content_version
            FROM contributions k
            LEFT JOIN chapters c ON c.novel_id = k.novel_id AND c.number = k.chapter
            WHERE k.novel_id = $1 AND ($2 = 'all' OR k.status = $2)
            ORDER BY k.created_at DESC LIMIT 200;
            """,
            novel_id, status,
        )
        return [
            Contribution(
                id=int(row["id"]), chapter=float(row["chapter"]),
                content=row["content"], base_version=int(row["base_version"]),
                status=row["status"], created_at=row["created_at"],
                from_user_id=int(row["from_user_id"]), base_content=row["base_content"],
                current_content_version=(
                    int(row["content_version"])
                    if row["content_version"] is not None else None
                ),
            )
            for row in rows
        ]

    async def get_contribution(
        self, novel_id: int, contribution_id: int
    ) -> tuple[float, str, int, int, str] | None:
        row = await self._connection.fetchrow(
            "SELECT chapter, content, from_user_id, base_version, status "
            "FROM contributions WHERE id = $1 AND novel_id = $2;",
            contribution_id, novel_id,
        )
        if row is None:
            return None
        return (
            float(row["chapter"]), row["content"], int(row["from_user_id"]),
            int(row["base_version"] or 1), row["status"],
        )

    async def mark_contribution_accepted(
        self, contribution_id: int, reviewer_id: int, content: str
    ) -> None:
        await self._connection.execute(
            "UPDATE contributions SET status = 'accepted', content = $3, "
            "reviewed_by = $2, reviewed_at = now() WHERE id = $1;",
            contribution_id, reviewer_id, content,
        )

    async def reject_contribution(
        self, novel_id: int, contribution_id: int, reviewer_id: int
    ) -> bool:
        updated = await self._connection.fetchval(
            "UPDATE contributions SET status = 'rejected', reviewed_by = $3, reviewed_at = now() "
            "WHERE id = $1 AND novel_id = $2 AND status = 'pending' RETURNING id;",
            contribution_id, novel_id, reviewer_id,
        )
        return updated is not None
