from __future__ import annotations

import json

from novelwiki.modules.acquisition.public import SourceDraft

from .importer import storage


class PostgresAcquisitionTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def create_source(self, novel_id: int, draft: SourceDraft) -> int:
        return int(await self._connection.fetchval(
            """
            INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw,
                                 chapter_offset, label)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id;
            """,
            novel_id, draft.adapter, draft.start_url, json.dumps(draft.config or {}),
            draft.language, draft.is_raw, draft.chapter_offset, draft.label,
        ))

    async def list_import_job_ids(self, novel_id: int) -> list[int]:
        rows = await self._connection.fetch(
            "SELECT id FROM import_jobs WHERE novel_id = $1;", novel_id
        )
        return [int(row["id"]) for row in rows]

    async def store_novel_asset(
        self, novel_id: int, data: bytes, mime: str | None, kind: str
    ) -> dict:
        return await storage.save_novel_asset(
            self._connection, novel_id, data, mime, kind
        )

    async def source_offset_state(
        self, source_id: int
    ) -> tuple[int, float]:
        row = await self._connection.fetchrow(
            "SELECT novel_id, chapter_offset FROM sources WHERE id = $1;", source_id
        )
        if row is None:
            raise ValueError(f"Source {source_id} not found.")
        return int(row["novel_id"]), float(row["chapter_offset"] or 0)

    async def set_source_offset(self, source_id: int, offset: float) -> None:
        await self._connection.execute(
            "UPDATE sources SET chapter_offset = $2 WHERE id = $1;", source_id, offset
        )

    async def import_source(self, source_id: int) -> dict | None:
        row = await self._connection.fetchrow(
            "SELECT id,novel_id,chapter_offset FROM sources WHERE id=$1;", source_id
        )
        return dict(row) if row else None

    async def source_metadata(self, source_id: int | None) -> dict:
        if source_id is None:
            return {"adapter": None, "is_raw": False}
        row = await self._connection.fetchrow(
            "SELECT adapter,is_raw FROM sources WHERE id=$1;", source_id
        )
        return dict(row) if row else {"adapter": None, "is_raw": False}

    async def replace_import_source(
        self, source_id: int, *, adapter: str, start_url: str, language: str,
        is_raw: bool, offset: float, label: str,
    ) -> None:
        await self._connection.execute(
            """
            UPDATE sources SET adapter=$2,start_url=$3,language=$4,is_raw=$5,
              chapter_offset=$6,label=$7 WHERE id=$1;
            """,
            source_id, adapter, start_url, language, is_raw, offset, label,
        )

    async def create_import_source(
        self, novel_id: int, *, adapter: str, start_url: str, language: str,
        is_raw: bool, offset: float, label: str,
    ) -> int:
        return int(await self._connection.fetchval(
            """
            INSERT INTO sources
              (novel_id,adapter,start_url,config,language,is_raw,chapter_offset,label)
            VALUES ($1,$2,$3,'{}'::jsonb,$4,$5,$6,$7) RETURNING id;
            """,
            novel_id, adapter, start_url, language, is_raw, offset, label,
        ))

    async def commit_import_asset(
        self, novel_id: int, job_id: int, sha256: str, extension: str,
        mime: str | None, kind: str, width: int | None, height: int | None,
    ) -> dict:
        await storage.commit_asset(
            self._connection, novel_id, job_id, sha256, extension, mime, kind,
            width, height,
        )
        return {
            "url": storage.asset_url(novel_id, sha256, extension),
            "width": width, "height": height, "mime": mime,
        }

    async def finalize_import_job(
        self, job_id: int, novel_id: int, source_id: int, stats: dict
    ) -> None:
        await self._connection.execute(
            """
            UPDATE import_jobs SET novel_id=$2,source_id=$3,status='committed',
              stage='committed',stats=$4::jsonb,error=NULL,updated_at=now()
            WHERE id=$1;
            """,
            job_id, novel_id, source_id, json.dumps(stats),
        )


class AcquisitionFilesystemCleanup:
    def cleanup_deleted_novel(self, novel_id: int, import_job_ids: list[int]) -> None:
        storage.cleanup_novel_assets(novel_id)
        for job_id in import_job_ids:
            storage.cleanup_job(job_id)
