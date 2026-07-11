"""Shared atomic claim primitive for API and AGY durable workers."""
from __future__ import annotations

from collections.abc import Iterable

from novelwiki.platform.database import get_db_pool
from novelwiki.modules.work.adapters.outbound import postgres as service


async def claim_next(
    *,
    execution_backend: str,
    worker_id: str,
    kinds: Iterable[str] | None = None,
) -> dict | None:
    if execution_backend not in ("api", "agy"):
        raise ValueError("execution_backend must be api or agy")
    allowed_kinds = list(kinds or service.KINDS)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE jobs j
            SET status='running', stage='claimed', attempts=j.attempts + 1,
                claim_token=$2, claimed_at=now(), updated_at=now()
            WHERE j.id = (
              SELECT id FROM jobs
              WHERE status=ANY($1::text[])
                AND execution_backend=$3
                AND kind=ANY($4::text[])
                AND (not_before IS NULL OR not_before <= now())
                AND cancel_requested_at IS NULL
              ORDER BY updated_at ASC
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            RETURNING j.*;
            """,
            list(service.TRIGGER_STATUSES), worker_id, execution_backend, allowed_kinds,
        )
    return service._row_to_job(row) if row else None
