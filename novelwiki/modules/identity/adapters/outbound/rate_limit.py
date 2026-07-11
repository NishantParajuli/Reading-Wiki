"""Small DB-backed fixed-window rate limits for auth endpoints."""
from __future__ import annotations

import datetime as dt

from novelwiki.modules.identity.application.rate_limits import (
    RateLimit,
    RateLimitExceeded,
    bucket_key,
)


def _retry_after(reset_at: dt.datetime) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=dt.timezone.utc)
    return max(1, int((reset_at - now).total_seconds()))


async def ensure_allowed(conn, key: str, rate: RateLimit) -> None:
    if rate.limit <= 0:
        return
    row = await conn.fetchrow(
        """
        SELECT count, reset_at
        FROM auth_rate_limits
        WHERE bucket_key = $1 AND reset_at > now();
        """,
        key,
    )
    if row is not None and row["count"] >= rate.limit:
        raise RateLimitExceeded(_retry_after(row["reset_at"]))


async def consume(conn, key: str, rate: RateLimit) -> None:
    if rate.limit <= 0:
        return
    row = await conn.fetchrow(
        """
        INSERT INTO auth_rate_limits (bucket_key, count, reset_at, updated_at)
        VALUES ($1, 1, now() + ($2::int * interval '1 second'), now())
        ON CONFLICT (bucket_key) DO UPDATE SET
          count = CASE
            WHEN auth_rate_limits.reset_at <= now() THEN 1
            ELSE auth_rate_limits.count + 1
          END,
          reset_at = CASE
            WHEN auth_rate_limits.reset_at <= now() THEN now() + ($2::int * interval '1 second')
            ELSE auth_rate_limits.reset_at
          END,
          updated_at = now()
        RETURNING count, reset_at;
        """,
        key,
        rate.window_seconds,
    )
    if row["count"] > rate.limit:
        raise RateLimitExceeded(_retry_after(row["reset_at"]))


async def clear(conn, key: str) -> None:
    await conn.execute("DELETE FROM auth_rate_limits WHERE bucket_key = $1;", key)


async def cleanup(conn) -> None:
    await conn.execute("DELETE FROM auth_rate_limits WHERE reset_at <= now();")
