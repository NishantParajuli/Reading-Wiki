from __future__ import annotations

import json

from ...application.ports import ImportAssetOwner
from ...public import SourceDraft


def _json_object(value) -> dict:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except (TypeError, ValueError):
            return {}
    return dict(value or {})


class PostgresAcquisitionRepository:
    """Acquisition-owned source/import/asset persistence."""

    def __init__(self, pool):
        self._pool = pool

    async def create_source(self, novel_id: int, draft: SourceDraft) -> int:
        async with self._pool.acquire() as connection:
            return int(await connection.fetchval(
                """
                INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw,
                                     chapter_offset, label)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id;
                """,
                novel_id,
                draft.adapter,
                draft.start_url,
                json.dumps(draft.config or {}),
                draft.language,
                draft.is_raw,
                draft.chapter_offset,
                draft.label,
            ))

    async def source_exists(self, novel_id: int, source_id: int) -> bool:
        async with self._pool.acquire() as connection:
            source = await connection.fetchval(
                "SELECT id FROM sources WHERE id = $1 AND novel_id = $2;",
                source_id,
                novel_id,
            )
        return source is not None

    async def update_source(
        self, source_id: int, fields: dict[str, object]
    ) -> int:
        allowed = {"chapter_offset", "start_url", "label", "language", "is_raw"}
        if not set(fields) <= allowed:
            raise ValueError("unsupported source field")
        mutable = dict(fields)
        renumbered = 0
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                if "chapter_offset" in mutable:
                    renumbered = await _update_source_offset(
                        connection, source_id, mutable.pop("chapter_offset")
                    )
                if mutable:
                    sets: list[str] = []
                    arguments: list[object] = []
                    for key, value in mutable.items():
                        arguments.append(value)
                        sets.append(f"{key} = ${len(arguments)}")
                    arguments.append(source_id)
                    await connection.execute(
                        f"UPDATE sources SET {', '.join(sets)} "
                        f"WHERE id = ${len(arguments)};",
                        *arguments,
                    )
        return renumbered

    async def novel_asset(
        self, novel_id: int, sha256: str, relative_path: str
    ) -> tuple[str, str | None] | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT path, mime FROM assets "
                "WHERE novel_id = $1 AND sha256 = $2 AND path = $3;",
                novel_id,
                sha256,
                relative_path,
            )
        return (str(row["path"]), row["mime"]) if row else None

    async def import_asset_owner(self, job_id: int) -> ImportAssetOwner | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT user_id, detected_meta FROM import_jobs WHERE id = $1;",
                job_id,
            )
        if row is None:
            return None
        return ImportAssetOwner(
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
            detected_meta=_json_object(row["detected_meta"]),
        )


async def _update_source_offset(connection, source_id: int, new_offset: float) -> int:
    """Atomically keep source chapters and reader pointers aligned after an offset edit."""
    row = await connection.fetchrow(
        "SELECT novel_id, chapter_offset FROM sources WHERE id = $1;", source_id
    )
    if row is None:
        raise ValueError(f"Source {source_id} not found.")
    novel_id = row["novel_id"]
    delta = float(new_offset) - float(row["chapter_offset"] or 0)
    renumbered = 0
    if delta != 0:
        has_codex_artifacts = await connection.fetchval(
            """
            WITH source_chapters AS (
                SELECT novel_id, number FROM chapters WHERE source_id = $1
            )
            SELECT
                EXISTS (SELECT 1 FROM chunks x JOIN source_chapters s ON (x.novel_id, x.chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM entities x JOIN source_chapters s ON (x.novel_id, x.first_seen_chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM entity_descriptions x JOIN source_chapters s ON (x.novel_id, x.chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM entity_aliases x JOIN source_chapters s ON (x.novel_id, x.revealed_at_chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM identity_links x JOIN source_chapters s ON (x.novel_id, x.revealed_at_chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM entity_facts x JOIN source_chapters s ON (x.novel_id, x.chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM relationships x JOIN source_chapters s ON (x.novel_id, x.chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM events x JOIN source_chapters s ON (x.novel_id, x.chapter) = (s.novel_id, s.number))
             OR EXISTS (SELECT 1 FROM extraction_state x JOIN source_chapters s ON (x.novel_id, x.chapter) = (s.novel_id, s.number));
            """,
            source_id,
        )
        if has_codex_artifacts:
            raise ValueError(
                "This source has codex artifacts built on its current chapter numbering; "
                "clear/rebuild the codex before changing the offset."
            )
        await connection.execute(
            """
            UPDATE bookmarks SET chapter = chapter + $2
            WHERE novel_id = $3
              AND chapter IN (SELECT number FROM chapters WHERE source_id = $1);
            """,
            source_id,
            delta,
            novel_id,
        )
        await connection.execute(
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
            source_id,
            delta,
            novel_id,
        )
        await connection.execute(
            "UPDATE chapters SET number = number + $2 + 1000000 WHERE source_id = $1;",
            source_id,
            delta,
        )
        status = await connection.execute(
            "UPDATE chapters SET number = number - 1000000 WHERE source_id = $1;",
            source_id,
        )
        try:
            renumbered = int(status.split()[-1])
        except (ValueError, IndexError):
            renumbered = 0
    await connection.execute(
        "UPDATE sources SET chapter_offset = $2 WHERE id = $1;",
        source_id,
        new_offset,
    )
    return renumbered
