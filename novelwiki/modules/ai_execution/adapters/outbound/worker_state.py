from __future__ import annotations

import json


class PostgresAgyWorkerStateRepository:
    def __init__(self, pool):
        self._pool = pool
        self._lock_connection = None

    async def load_user(self, user_id: int) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM users WHERE id=$1;", user_id)
        return dict(row) if row else None

    async def write_heartbeat(self, **fields) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO ai_worker_heartbeats
                  (worker_id,backend,status,version,plugin_version,plugin_sha256,
                   details,heartbeat_at,started_at)
                VALUES ($1,'agy',$2,$3,$4,$5,$6,now(),now())
                ON CONFLICT (worker_id) DO UPDATE SET status=EXCLUDED.status,
                  version=EXCLUDED.version,plugin_version=EXCLUDED.plugin_version,
                  plugin_sha256=EXCLUDED.plugin_sha256,details=EXCLUDED.details,
                  heartbeat_at=now();
                """,
                fields["worker_id"], fields["status"], fields.get("version"),
                fields["plugin_version"], fields.get("plugin_sha256"),
                json.dumps(fields.get("details") or {}),
            )

    async def orphan_runs(self) -> list[dict]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id,job_id,workload,status,workspace_relpath,
                       process_group_id,process_started_at
                FROM ai_execution_runs
                WHERE backend='agy' AND status IN ('preparing','running','validating');
                """
            )
        return [dict(row) for row in rows]

    async def mark_orphan_lost(self, run_id: int, release_translation: bool) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE ai_execution_runs SET status='worker_lost',
                  failure_code='worker_lost',
                  error_summary='Worker exited before a complete artifact was ready.',
                  finished_at=now()
                WHERE id=$1 AND status IN ('preparing','running','validating');
                """,
                run_id,
            )
            if release_translation:
                await connection.execute(
                    """
                    UPDATE chapters SET translation_status='failed',
                      translation_run_id=NULL
                    WHERE translation_run_id=$1 AND translation_status='translating';
                    """,
                    run_id,
                )

    async def active_job_count(self, user_id: int) -> int:
        async with self._pool.acquire() as connection:
            return int(await connection.fetchval(
                """
                SELECT count(*) FROM jobs WHERE user_id=$1
                  AND execution_backend='agy'
                  AND status IN ('queued','running','waiting_provider');
                """,
                user_id,
            ) or 0)

    async def fallback_to_api(
        self, job_id: int, model: str, max_attempts: int, error: str
    ) -> bool:
        async with self._pool.acquire() as connection:
            changed = await connection.fetchrow(
                """
                UPDATE jobs SET execution_backend='api',backend_fallback_from='agy',
                  backend_model=$2,backend_fallback_allowed=FALSE,status='queued',
                  stage='AGY failed; switching to API',attempts=0,max_attempts=$3,
                  error=$4,claim_token=NULL,claimed_at=NULL,not_before=NULL,
                  cancel_requested_at=NULL,updated_at=now()
                WHERE id=$1 AND status='running' RETURNING id;
                """,
                job_id, model, max_attempts, error,
            )
        return changed is not None

    async def acquire_subscription_lock(self, key: str) -> bool:
        connection = await self._pool.acquire()
        try:
            locked = bool(await connection.fetchval(
                "SELECT pg_try_advisory_lock(hashtext($1));", key,
            ))
            if locked:
                self._lock_connection = connection
                return True
        except Exception:
            await self._pool.release(connection)
            raise
        await self._pool.release(connection)
        return False

    async def release_subscription_lock(self, key: str) -> None:
        connection, self._lock_connection = self._lock_connection, None
        if connection is None:
            return
        try:
            await connection.execute(
                "SELECT pg_advisory_unlock(hashtext($1));", key,
            )
        finally:
            await self._pool.release(connection)
