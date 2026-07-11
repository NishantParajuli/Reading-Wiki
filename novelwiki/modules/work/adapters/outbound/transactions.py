from __future__ import annotations


class PostgresWorkTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def increment_quota_consumed(self, job_id: int, units: int) -> None:
        if units <= 0:
            return
        result = await self._connection.execute(
            """
            UPDATE jobs SET quota_consumed = quota_consumed + $2, updated_at=now()
            WHERE id=$1 AND quota_finalized=FALSE
              AND quota_consumed + $2 <= quota_reserved;
            """,
            job_id, int(units),
        )
        if result.endswith("0"):
            raise RuntimeError("job quota reservation is missing, finalized, or exhausted")
