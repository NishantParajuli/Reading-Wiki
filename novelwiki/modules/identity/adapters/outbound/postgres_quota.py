from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from typing import Any

from ...application.quota import QUOTA_KINDS
from ...application.quota import current_period


class PostgresQuotaRepository:
    def __init__(self, *, pool: Any = None, connection: Any = None):
        if pool is None and connection is None:
            raise ValueError("pool or connection is required")
        self._pool = pool
        self._connection = connection

    @asynccontextmanager
    async def _use_connection(self, *, transaction: bool = False):
        if self._connection is not None:
            yield self._connection
            return
        async with self._pool.acquire() as connection:
            if transaction:
                async with connection.transaction():
                    yield connection
            else:
                yield connection

    @staticmethod
    def _kind(kind: str) -> str:
        if kind not in QUOTA_KINDS:
            raise ValueError(f"unknown quota kind: {kind}")
        return kind

    async def get_usage(self, user_id: int, period: dt.date) -> dict[str, int]:
        async with self._use_connection() as connection:
            row = await connection.fetchrow(
                "SELECT translated_chapters, ocr_pages, codex_builds, tts_chapters "
                "FROM quota_usage WHERE user_id = $1 AND period = $2;",
                user_id,
                period,
            )
        return {kind: int(row[kind]) if row else 0 for kind in QUOTA_KINDS}

    async def bump(
        self, user_id: int, period: dt.date, kind: str, units: int
    ) -> None:
        kind = self._kind(kind)
        async with self._use_connection() as connection:
            await connection.execute(
                "INSERT INTO quota_usage (user_id, period) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING;",
                user_id,
                period,
            )
            await connection.execute(
                f"UPDATE quota_usage SET {kind} = {kind} + $3 "
                "WHERE user_id = $1 AND period = $2;",
                user_id,
                period,
                units,
            )

    async def try_reserve(
        self,
        user_id: int,
        period: dt.date,
        kind: str,
        units: int,
        limit: int,
    ) -> bool:
        kind = self._kind(kind)
        async with self._use_connection(transaction=True) as connection:
            await connection.execute(
                "INSERT INTO quota_usage (user_id, period) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING;",
                user_id,
                period,
            )
            used = await connection.fetchval(
                f"SELECT {kind} FROM quota_usage "
                "WHERE user_id = $1 AND period = $2 FOR UPDATE;",
                user_id,
                period,
            )
            if used + units > limit:
                return False
            await connection.execute(
                f"UPDATE quota_usage SET {kind} = {kind} + $3 "
                "WHERE user_id = $1 AND period = $2;",
                user_id,
                period,
                units,
            )
            return True

    async def refund(
        self, user_id: int, period: dt.date, kind: str, units: int
    ) -> int:
        kind = self._kind(kind)
        async with self._use_connection(transaction=True) as connection:
            used = await connection.fetchval(
                f"SELECT {kind} FROM quota_usage "
                "WHERE user_id = $1 AND period = $2 FOR UPDATE;",
                user_id,
                period,
            )
            if used is None:
                return 0
            give = min(int(units), int(used))
            if give <= 0:
                return 0
            await connection.execute(
                f"UPDATE quota_usage SET {kind} = {kind} - $3 "
                "WHERE user_id = $1 AND period = $2;",
                user_id,
                period,
                give,
            )
            return give


class PostgresQuotaTransactionService:
    """Identity quota capability bound to a composition-owned transaction."""

    def __init__(self, connection: Any):
        self._repository = PostgresQuotaRepository(connection=connection)

    async def refund(self, user_id: int, kind: str, units: int = 1) -> int:
        if user_id is None or units <= 0:
            return 0
        return await self._repository.refund(
            user_id, current_period(), kind, units
        )
