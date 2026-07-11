from __future__ import annotations

import datetime as dt
from typing import Any

from novelwiki.modules.identity.adapters.outbound.tokens import hash_token, new_token
from novelwiki.platform.config import settings


async def create_session(connection: Any, user_id: int, user_agent: str | None = None) -> str:
    """Create a session row and return the raw token."""
    token = new_token()
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.SESSION_TTL_DAYS)
    await connection.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at, user_agent) VALUES ($1, $2, $3, $4);",
        hash_token(token), user_id, expires, (user_agent or "")[:400],
    )
    return token


async def revoke_session(connection: Any, token: str) -> None:
    await connection.execute("DELETE FROM sessions WHERE token_hash = $1;", hash_token(token))


async def revoke_user_sessions(connection: Any, user_id: int) -> None:
    await connection.execute("DELETE FROM sessions WHERE user_id = $1;", user_id)


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
