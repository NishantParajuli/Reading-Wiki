from __future__ import annotations

from datetime import timedelta
from typing import Any


class PostgresWorkerStateRepository:
    def __init__(self, pool: Any):
        self._pool = pool

    async def load_user(self, user_id: int) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM users WHERE id = $1;", user_id
            )
        return dict(row) if row else None

    async def pending_translations(
        self,
        novel_id: int,
        from_chapter: float | None,
        to_chapter: float | None,
        force: bool,
    ) -> list[float]:
        conditions = ["novel_id = $1", "original_text IS NOT NULL"]
        arguments: list[object] = [novel_id]
        if not force:
            conditions.append("content IS NULL")
        if from_chapter is not None:
            arguments.append(from_chapter)
            conditions.append(f"number >= ${len(arguments)}")
        if to_chapter is not None:
            arguments.append(to_chapter)
            conditions.append(f"number <= ${len(arguments)}")
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT number FROM chapters WHERE {' AND '.join(conditions)} "
                "ORDER BY number ASC;",
                *arguments,
            )
        return [float(row["number"]) for row in rows]

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
