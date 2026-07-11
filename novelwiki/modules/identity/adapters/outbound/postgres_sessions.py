from __future__ import annotations

from typing import Any


class PostgresSessionRepository:
    def __init__(self, pool: Any):
        self._pool = pool

    async def load_active_user(self, token_hash: str) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT u.* FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = $1 AND s.expires_at > now() AND u.status = 'active';
                """,
                token_hash,
            )
            if row is not None:
                await connection.execute(
                    "UPDATE sessions SET last_seen_at = now() WHERE token_hash = $1;",
                    token_hash,
                )
        return dict(row) if row is not None else None
