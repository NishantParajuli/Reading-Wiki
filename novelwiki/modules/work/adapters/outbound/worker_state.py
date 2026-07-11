from __future__ import annotations

from datetime import timedelta
from typing import Any


class PostgresWorkerStateRepository:
    def __init__(self, pool: Any):
        self._pool = pool

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

    async def revoked_job_ids(self, user_id: int, kinds: list[str]) -> list[int]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT id FROM jobs WHERE user_id=$1 AND execution_backend='agy' "
                "AND kind=ANY($2::text[]) AND status=ANY($3::text[]);",
                user_id, kinds, ["queued", "running", "waiting_provider"],
            )
        return [int(row["id"]) for row in rows]

    async def renew_lease(self, job_id: int, token: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE jobs SET claimed_at = now() WHERE id = $1 "
                "AND claim_token = $2 AND status = 'running';",
                job_id, token,
            )

    async def stale_leases(self, lease: timedelta) -> list[dict]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT id, attempts, max_attempts, cancel_requested_at FROM jobs "
                "WHERE status = 'running' AND "
                "(claimed_at IS NULL OR claimed_at < now() - $1::interval);",
                lease,
            )
        return [dict(row) for row in rows]

    async def cancel_stale_lease(self, job_id: int, lease: timedelta) -> bool:
        async with self._pool.acquire() as connection:
            changed = await connection.fetchrow(
                """
                UPDATE jobs SET status='canceled',
                  stage='canceled (worker lost after request)',
                  claim_token=NULL,claimed_at=NULL,updated_at=now()
                WHERE id=$1 AND status='running' AND cancel_requested_at IS NOT NULL
                  AND (claimed_at IS NULL OR claimed_at < now()-$2::interval)
                RETURNING id;
                """,
                job_id, lease,
            )
        return changed is not None

    async def fail_stale_lease(self, job_id: int, lease: timedelta) -> bool:
        async with self._pool.acquire() as connection:
            changed = await connection.fetchrow(
                "UPDATE jobs SET status='failed', stage='failed (worker lost)', "
                "error=COALESCE(error, 'Worker lost the job before it finished "
                "(lease expired).'), claim_token=NULL, claimed_at=NULL, updated_at=now() "
                "WHERE id=$1 AND status='running' AND "
                "(claimed_at IS NULL OR claimed_at < now() - $2::interval) RETURNING id;",
                job_id, lease,
            )
        return changed is not None

    async def requeue_stale_lease(self, job_id: int, lease: timedelta) -> bool:
        async with self._pool.acquire() as connection:
            changed = await connection.fetchrow(
                "UPDATE jobs SET status='queued', stage='requeued (lease expired)', "
                "claim_token=NULL, claimed_at=NULL, updated_at=now() "
                "WHERE id=$1 AND status='running' AND "
                "(claimed_at IS NULL OR claimed_at < now() - $2::interval) RETURNING id;",
                job_id, lease,
            )
        return changed is not None

    async def release_due_provider_waits(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE jobs SET status='queued', stage='queued after provider wait',
                  not_before=NULL, updated_at=now()
                WHERE status='waiting_provider' AND not_before IS NOT NULL
                  AND not_before <= now();
                """
            )
