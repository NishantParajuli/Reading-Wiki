"""Identity-owned startup maintenance operations."""

from __future__ import annotations


async def cleanup_expired_identity_state(pool) -> None:
    from . import rate_limit

    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM sessions WHERE expires_at <= now();")
        await connection.execute(
            "DELETE FROM email_tokens WHERE used_at IS NOT NULL OR expires_at <= now();"
        )
        await rate_limit.cleanup(connection)
