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
        allowed = {"start_url", "label", "language", "is_raw"}
        if not set(fields) <= allowed:
            raise ValueError("unsupported source field")
        mutable = dict(fields)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
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
        return 0

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
