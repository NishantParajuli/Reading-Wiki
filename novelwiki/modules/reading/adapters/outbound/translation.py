from __future__ import annotations

import hashlib
from decimal import Decimal


def _source_sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _job(row) -> dict:
    return dict(row) if row is not None else {}


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

    async def stage_translation_batch(
        self, novel_id: int, chapters: list[float], run_id, force: bool
    ) -> list[dict]:
        if not chapters:
            return []
        staged: list[dict] = []
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                rows = await connection.fetch(
                    """
                    SELECT number, title, original_text, content, language,
                           translation_status, content_version
                    FROM chapters
                    WHERE novel_id=$1 AND number=ANY($2::numeric[])
                    ORDER BY number ASC FOR UPDATE;
                    """,
                    novel_id, [Decimal(str(number)) for number in chapters],
                )
                for row in rows:
                    if not row["original_text"] or (row["content"] and not force):
                        continue
                    if row["translation_status"] == "translating":
                        continue
                    digest = _source_sha256(row["original_text"])
                    await connection.execute(
                        """
                        UPDATE chapters SET translation_status='translating',
                          translation_run_id=$3, translation_source_sha256=$4
                        WHERE novel_id=$1 AND number=$2;
                        """,
                        novel_id, row["number"], run_id, digest,
                    )
                    staged.append({
                        "number": float(row["number"]), "title": row["title"],
                        "original_text": row["original_text"],
                        "language": row["language"] or "the source language",
                        "source_sha256": digest,
                        "source_content_version": int(row["content_version"] or 1),
                    })
        return staged

    async def reset_staged_translations(self, run_id, status: str) -> int:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                """
                UPDATE chapters SET translation_status=$2, translation_run_id=NULL
                WHERE translation_run_id=$1 AND translation_status='translating';
                """,
                run_id, status,
            )
        return int(result.rsplit(" ", 1)[-1])

    async def translation_candidate(self, novel_id: int, chapter: float) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT title, original_text, content, translation_status, language,
                       content_version, translation_run_id
                FROM chapters WHERE novel_id=$1 AND number=$2;
                """,
                novel_id, chapter,
            )
        return _job(row) or None

    async def mark_translation_started(
        self, novel_id: int, chapter: float, source_hash: str
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE chapters SET translation_status='translating', "
                "translation_run_id=NULL, translation_source_sha256=$3 "
                "WHERE novel_id=$1 AND number=$2;",
                novel_id, chapter, source_hash,
            )

    async def mark_translation_failed(
        self, novel_id: int, chapter: float, only_unowned: bool = False
    ) -> None:
        predicate = (
            " AND translation_run_id IS NULL AND translation_status='translating'"
            if only_unowned else ""
        )
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE chapters SET translation_status='failed' "
                f"WHERE novel_id=$1 AND number=$2{predicate};",
                novel_id, chapter,
            )

    async def pending_after(
        self, novel_id: int, after: float, count: int
    ) -> list[float]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT number FROM chapters
                WHERE novel_id=$1 AND number>$2
                  AND content IS NULL AND original_text IS NOT NULL
                  AND translation_status IN ('none','pending','failed')
                ORDER BY number ASC LIMIT $3;
                """,
                novel_id, after, count,
            )
        return [float(row["number"]) for row in rows]

    async def translation_range(
        self, novel_id: int, start: float | None, end: float | None, force: bool
    ) -> list[float]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT number FROM chapters
                WHERE novel_id=$1 AND original_text IS NOT NULL
                  AND ($4 OR content IS NULL)
                  AND ($2::numeric IS NULL OR number >= $2)
                  AND ($3::numeric IS NULL OR number <= $3)
                ORDER BY number ASC;
                """,
                novel_id, start, end, force,
            )
        return [float(row["number"]) for row in rows]

    async def agy_pending(
        self, novel_id: int, start: float | None, end: float | None, force: bool
    ) -> list[float]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT number FROM chapters WHERE novel_id=$1 "
                "AND original_text IS NOT NULL AND translation_status<>'translating' "
                "AND ($4 OR content IS NULL) AND ($2::numeric IS NULL OR number>=$2) "
                "AND ($3::numeric IS NULL OR number<=$3) ORDER BY number;",
                novel_id, start, end, force,
            )
        return [float(row["number"]) for row in rows]

    async def source_lengths(
        self, novel_id: int, chapters: list[float]
    ) -> dict[float, int]:
        if not chapters:
            return {}
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT number,length(original_text) AS chars FROM chapters "
                "WHERE novel_id=$1 AND number=ANY($2::numeric[]);", novel_id, chapters,
            )
        return {float(row["number"]): int(row["chars"] or 0) for row in rows}


class PostgresReadingTranslationTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def commit_translation(
        self, novel_id: int, chapter: float, *, expected_source_hash: str,
        expected_content_version: int, translated_title: str | None,
        translation: str, model_label: str, run_id,
    ) -> dict:
        row = await self._connection.fetchrow(
            """
            SELECT original_text, content, content_version, translation_status,
                   translation_run_id, translation_source_sha256
            FROM chapters WHERE novel_id=$1 AND number=$2 FOR UPDATE;
            """,
            novel_id, chapter,
        )
        if not row:
            raise RuntimeError("chapter no longer exists")
        actual_hash = _source_sha256(row["original_text"])
        if (run_id is not None and row["translation_run_id"] == run_id
                and row["translation_status"] == "done"
                and row["translation_source_sha256"] == expected_source_hash):
            return {"status": "done", "content": row["content"], "idempotent": True}
        if (actual_hash != expected_source_hash
                or int(row["content_version"] or 1) != int(expected_content_version)):
            raise RuntimeError("chapter source or content version changed")
        if run_id is not None and row["translation_run_id"] != run_id:
            raise RuntimeError("chapter is no longer staged by this AGY run")
        if run_id is None and row["translation_run_id"] is not None:
            raise RuntimeError("chapter is staged by another translation worker")
        title = (translated_title or "").strip() or None
        await self._connection.execute(
            """
            UPDATE chapters SET title=COALESCE($3,title), content=$4,
              is_translated=TRUE, translation_status='done', translation_model=$5,
              word_count=$6, content_version=content_version+1,
              translation_run_id=$7, translation_source_sha256=$8
            WHERE novel_id=$1 AND number=$2;
            """,
            novel_id, chapter, title, translation.strip(), model_label,
            len(translation.split()), run_id, expected_source_hash,
        )
        await self._connection.execute(
            """
            UPDATE chapter_overlays SET conflict=TRUE, updated_at=now()
            WHERE novel_id=$1 AND chapter=$2
              AND base_version < (SELECT content_version FROM chapters
                                  WHERE novel_id=$1 AND number=$2);
            """,
            novel_id, chapter,
        )
        return {"status": "done", "content": translation.strip(), "idempotent": False}
