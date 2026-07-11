from __future__ import annotations


class PostgresIdentityWorkerLookup:
    def __init__(self, pool):
        self._pool = pool

    async def load_user(self, user_id: int) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM users WHERE id=$1;", user_id)
        return dict(row) if row else None
