from __future__ import annotations

import json


_JSON_FIELDS = {"detected_meta", "plan", "stats", "cost_estimate", "progress", "options"}


class PostgresImportWorkerRepository:
    """Acquisition-owned durable import state; no worker transport concerns."""

    def __init__(self, pool):
        self._pool = pool

    async def create_job(self, format: str, original_path: str, file_sha256,
                         options: dict, detected_meta: dict, status: str,
                         user_id: int | None) -> int:
        async with self._pool.acquire() as connection:
            return int(await connection.fetchval(
                """
                INSERT INTO import_jobs
                  (format,original_path,file_sha256,options,detected_meta,status,user_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id;
                """,
                format, original_path, file_sha256, json.dumps(options),
                json.dumps(detected_meta), status, user_id,
            ))

    async def get_job(self, job_id: int):
        async with self._pool.acquire() as connection:
            return await connection.fetchrow("SELECT * FROM import_jobs WHERE id=$1;", job_id)

    async def list_jobs(self, limit: int, user_id: int | None):
        async with self._pool.acquire() as connection:
            if user_id is None:
                return await connection.fetch(
                    "SELECT * FROM import_jobs ORDER BY created_at DESC LIMIT $1;", limit
                )
            return await connection.fetch(
                "SELECT * FROM import_jobs WHERE user_id=$1 "
                "ORDER BY created_at DESC LIMIT $2;", user_id, limit,
            )

    async def update_job(self, job_id: int, fields: dict) -> None:
        if not fields:
            return
        sets, arguments = [], []
        for key, value in fields.items():
            arguments.append(
                json.dumps(value) if key in _JSON_FIELDS and value is not None else value
            )
            sets.append(f"{key}=${len(arguments)}")
        arguments.append(job_id)
        async with self._pool.acquire() as connection:
            await connection.execute(
                f"UPDATE import_jobs SET {', '.join(sets)},updated_at=now() "
                f"WHERE id=${len(arguments)};", *arguments,
            )

    async def touch_job(self, job_id: int) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE import_jobs SET updated_at=now() WHERE id=$1;", job_id
            )

    async def batch_siblings(self, batch_id: str):
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                "SELECT * FROM import_jobs WHERE options->>'batch_id'=$1 ORDER BY id;",
                batch_id,
            )

    async def duplicate_imports(self, sha256: str, exclude_job_id: int | None):
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                """
                SELECT id,novel_id,status,created_at FROM import_jobs
                WHERE file_sha256=$1 AND ($2::bigint IS NULL OR id<>$2)
                ORDER BY created_at DESC;
                """,
                sha256, exclude_job_id,
            )

    async def recover_stale_leases(self, markers, trigger: str, lease):
        async with self._pool.acquire() as connection:
            return await connection.execute(
                "UPDATE import_jobs SET status=$2,stage='requeued (lease expired)',"
                "claim_token=NULL,claimed_at=NULL WHERE status=ANY($1::text[]) "
                "AND (claimed_at IS NULL OR claimed_at<now()-$3::interval);",
                list(markers), trigger, lease,
            )

    async def stale_upload_ids(self, ttl):
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT id FROM import_jobs WHERE status='receiving' "
                "AND updated_at<now()-$1::interval;", ttl,
            )
        return [int(row["id"]) for row in rows]

    async def delete_stale_upload(self, job_id: int, ttl) -> bool:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                "DELETE FROM import_jobs WHERE id=$1 AND status='receiving' "
                "AND updated_at<now()-$2::interval;", job_id, ttl,
            )
        return not result.endswith(" 0")

    async def reactivate_paused(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE import_jobs SET status='ocr_pending',"
                "stage='resuming OCR (budget available)',claim_token=NULL,claimed_at=NULL "
                "WHERE status='ocr_paused';"
            )

    async def claim_next(self, statuses, worker_id: str):
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(
                """
                UPDATE import_jobs j SET
                  status=CASE j.status WHEN 'uploaded' THEN 'parsing'
                    WHEN 'ocr_pending' THEN 'ocr_running'
                    WHEN 'committing' THEN 'commit_running' ELSE j.status END,
                  stage='claimed',claim_token=$2,claimed_at=now(),updated_at=now()
                WHERE j.id=(SELECT id FROM import_jobs WHERE status=ANY($1::text[])
                  ORDER BY updated_at ASC FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING j.*;
                """,
                list(statuses), worker_id,
            )

    async def renew_lease(self, job_id: int, token: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE import_jobs SET claimed_at=now() WHERE id=$1 AND claim_token=$2;",
                job_id, token,
            )
