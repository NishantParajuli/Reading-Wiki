from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class PostgresReadingIngestionTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def resume_url(self, source_id: int) -> str | None:
        return await self._connection.fetchval(
            "SELECT url FROM chapters WHERE source_id=$1 AND url IS NOT NULL "
            "ORDER BY number DESC LIMIT 1;", source_id,
        )

    async def source_versions(self, source_id: int) -> dict[float, int]:
        rows = await self._connection.fetch(
            "SELECT number,content_version FROM chapters WHERE source_id=$1;", source_id
        )
        return {float(row["number"]): int(row["content_version"] or 1) for row in rows}

    async def delete_source_chapters(self, source_id: int) -> None:
        await self._connection.execute("DELETE FROM chapters WHERE source_id=$1;", source_id)

    async def mark_overlay_conflicts(
        self, novel_id: int, chapters: tuple[float, ...]
    ) -> None:
        if chapters:
            await self._connection.execute(
                "UPDATE chapter_overlays SET conflict=TRUE,updated_at=now() "
                "WHERE novel_id=$1 AND chapter=ANY($2::numeric[]);",
                novel_id, list(chapters),
            )

    async def other_source_numbers(self, novel_id: int, source_id: int) -> set[float]:
        rows = await self._connection.fetch(
            "SELECT number FROM chapters WHERE novel_id=$1 AND source_id IS DISTINCT FROM $2;",
            novel_id, source_id,
        )
        return {float(row["number"]) for row in rows}

    async def preserve_content_version(
        self, novel_id: int, chapter: float, minimum: int
    ) -> int:
        actual = await self._connection.fetchval(
            "UPDATE chapters SET content_version=GREATEST(COALESCE(content_version,1),$3) "
            "WHERE novel_id=$1 AND number=$2 RETURNING content_version;",
            novel_id, chapter, minimum,
        )
        version = int(actual or minimum)
        await self._connection.execute(
            "UPDATE chapter_overlays SET conflict=TRUE,updated_at=now() "
            "WHERE novel_id=$1 AND chapter=$2 AND base_version<$3;",
            novel_id, chapter, version,
        )
        return version

    async def upsert_ingested_chapter(
        self, source: dict, number: float, chapter: object, force: bool,
        *, kind: str = "chapter", part_label: str | None = None,
        minimum_content_version: int | None = None,
    ) -> bool:
        novel_id = int(source["novel_id"])
        existing = await self._connection.fetchrow(
            "SELECT title,content,original_text,content_version FROM chapters "
            "WHERE novel_id=$1 AND number=$2;", novel_id, number,
        )
        if existing and not force:
            return False
        content_text = getattr(chapter, "content", None) or ""
        is_raw = bool(source.get("is_raw"))
        language = source.get("language")
        word_count = (
            len(re.sub(r"\s+", "", content_text))
            if is_raw or language in ("zh", "ja", "ko")
            else len(content_text.split())
        )
        original_text, content = (content_text, None) if is_raw else (None, content_text)
        translation_status = "pending" if is_raw else "none"
        base_changed = bool(existing and (
            existing["content"] != content or existing["original_text"] != original_text
        ))
        new_version = await self._connection.fetchval(
            """
            INSERT INTO chapters
              (novel_id,number,source_id,title,url,raw_html,original_text,content,
               language,is_translated,translation_status,word_count,kind,part_label)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,FALSE,$10,$11,$12,$13)
            ON CONFLICT (novel_id,number) DO UPDATE SET
              source_id=EXCLUDED.source_id,title=EXCLUDED.title,url=EXCLUDED.url,
              raw_html=EXCLUDED.raw_html,original_text=EXCLUDED.original_text,
              content=EXCLUDED.content,language=EXCLUDED.language,
              is_translated=EXCLUDED.is_translated,
              translation_status=EXCLUDED.translation_status,
              word_count=EXCLUDED.word_count,kind=EXCLUDED.kind,
              part_label=EXCLUDED.part_label,scraped_at=now(),
              content_version=GREATEST(
                CASE WHEN $14 THEN COALESCE(chapters.content_version,1)+1
                     ELSE COALESCE(chapters.content_version,1) END,
                COALESCE($15,1))
            RETURNING content_version;
            """,
            novel_id, number, source["id"], getattr(chapter, "title", None),
            getattr(chapter, "url", None), getattr(chapter, "raw_html", None),
            original_text, content, language, translation_status, word_count,
            kind, part_label, base_changed, minimum_content_version,
        )
        if base_changed or (minimum_content_version and int(new_version or 1) >= minimum_content_version):
            await self._connection.execute(
                "UPDATE chapter_overlays SET conflict=TRUE,updated_at=now() "
                "WHERE novel_id=$1 AND chapter=$2 AND base_version<$3;",
                novel_id, number, int(new_version or 1),
            )
        logger.info("Saved Chapter %s: %r (%s words)", number, getattr(chapter, "title", None), word_count)
        return True


class PostgresReadingIngestionGateway:
    def __init__(self, pool):
        self._pool = pool

    async def resume_url(self, source_id: int) -> str | None:
        async with self._pool.acquire() as connection:
            return await PostgresReadingIngestionTransactionService(connection).resume_url(source_id)

    async def upsert_ingested_chapter(self, *args, **kwargs) -> bool:
        async with self._pool.acquire() as connection:
            return await PostgresReadingIngestionTransactionService(
                connection
            ).upsert_ingested_chapter(*args, **kwargs)
