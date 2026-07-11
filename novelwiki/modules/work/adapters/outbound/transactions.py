from __future__ import annotations

from novelwiki.modules.work.application.contracts import JobQuotaSettlement


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


class PostgresWorkQuotaFinalizationTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def finalize_quota(
        self, job_id: int, success: bool
    ) -> JobQuotaSettlement | None:
        row = await self._connection.fetchrow(
            """
            UPDATE jobs SET
              quota_finalized = TRUE,
              quota_consumed = CASE
                WHEN $2 AND NOT (execution_backend='agy' AND kind='translate')
                THEN quota_reserved ELSE quota_consumed END,
              updated_at = now()
            WHERE id = $1 AND quota_finalized = FALSE
            RETURNING user_id, novel_id, quota_kind, quota_reserved, quota_consumed;
            """,
            job_id,
            success,
        )
        if row is None:
            return None
        return JobQuotaSettlement(
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
            novel_id=int(row["novel_id"]) if row["novel_id"] is not None else None,
            quota_kind=row["quota_kind"],
            refundable_units=max(
                0,
                int(row["quota_reserved"] or 0) - int(row["quota_consumed"] or 0),
            ),
        )
