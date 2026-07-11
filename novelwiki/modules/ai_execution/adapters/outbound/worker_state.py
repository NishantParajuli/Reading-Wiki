from __future__ import annotations

import json


class PostgresAgyWorkerStateRepository:
    def __init__(self, pool):
        self._pool = pool
        self._lock_connection = None

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

    async def resumable_runs(self, job_id: int, workloads: tuple[str, ...]) -> list[dict]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT id,parent_run_id,workload,workspace_relpath,input_sha256 "
                "FROM ai_execution_runs WHERE job_id=$1 AND workload=ANY($2::text[]) "
                "AND status='validating' ORDER BY created_at;",
                job_id, list(workloads),
            )
        return [dict(row) for row in rows]

    async def mark_orphan_lost(self, run_id: int) -> None:
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
