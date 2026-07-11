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


class AcquisitionFilesystemCleanup:
    def cleanup_deleted_novel(self, novel_id: int, import_job_ids: list[int]) -> None:
        storage.cleanup_novel_assets(novel_id)
        for job_id in import_job_ids:
            storage.cleanup_job(job_id)
