"""Read-side AI cost controls (denial-of-wallet guards).

`novelwiki.quota` meters *monthly* spend for costly writes (translation, OCR, codex,
TTS). This module adds the short-window controls the read-side AI paths need — the
agentic Q&A (`/ask`) and entity-profile synthesis — which each fan out to embeddings,
rerank, and several model calls per uncached request:

  * a verified-email spend gate (reuses ``quota.require_spend_allowed``),
  * a fixed per-hour cap on how many *uncached* AI reads a user may trigger
    (reuses the durable ``auth_rate_limits`` fixed-window counter), and
  * a small per-user concurrency ceiling backed by the self-expiring
    ``ai_request_locks`` table so a burst of parallel requests can't stampede.

Cache hits must never reach these gates — callers check the cache first and only spend
gate/rate/concurrency on a miss. Admins (``quota.is_exempt``) bypass the rate and
concurrency limits, exactly as they bypass monthly quota.
"""
from __future__ import annotations

import contextlib

from novelwiki.kernel.errors import Forbidden, RateLimited
from novelwiki.platform.auth import rate_limit
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool


def require_ask_spend_allowed(user: dict) -> None:
    """403 unless the account may trigger costed AI work (verified email, or admin)."""
    if user.get("role") != "admin" and (
        user.get("status", "active") != "active" or not user.get("email_verified")
    ):
        raise Forbidden(
            "Verify your email to use scrape, translation, OCR, codex, or import features."
        )


async def consume_ask_rate(user: dict, kind: str = "ask") -> None:
    """Charge one unit against the per-user hourly cap on uncached AI reads (429 if over).

    Only called on a cache miss, so cache hits are free. Each ``kind`` gets its own
    hourly budget. Admins are exempt.
    """
    if user.get("role") == "admin":
        return
    limit = settings.ASK_MAX_UNIQUE_PER_USER_HOUR
    rate = rate_limit.RateLimit(limit=limit, window_seconds=3600)
    key = rate_limit.bucket_key(f"ai:{kind}:user", str(user["id"]))
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            await rate_limit.consume(conn, key, rate)
        except rate_limit.RateLimitExceeded as exc:
            raise RateLimited(
                "You've made too many AI requests this hour. Please wait and try again.",
                retry_after=exc.retry_after,
            )


async def _acquire_slot(user_id: int, kind: str, max_concurrent: int, ttl_seconds: int) -> int | None:
    """Atomically claim a concurrency slot for (user, kind). Returns the lock id, or None
    if the user already holds ``max_concurrent`` live slots. A per-(user,kind) advisory
    lock serializes the check-and-insert so it is correct across workers/processes."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Serialize concurrent acquirers for this exact (user, kind) bucket.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0));", f"{user_id}:{kind}",
            )
            # Reclaim any slots whose owner died before releasing them.
            await conn.execute("DELETE FROM ai_request_locks WHERE expires_at <= now();")
            active = await conn.fetchval(
                "SELECT count(*) FROM ai_request_locks WHERE user_id = $1 AND kind = $2;",
                user_id, kind,
            )
            if active >= max_concurrent:
                return None
            return await conn.fetchval(
                """
                INSERT INTO ai_request_locks (user_id, kind, expires_at)
                VALUES ($1, $2, now() + ($3::int * interval '1 second'))
                RETURNING id;
                """,
                user_id, kind, ttl_seconds,
            )


async def _release_slot(lock_id: int) -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM ai_request_locks WHERE id = $1;", lock_id)


@contextlib.asynccontextmanager
async def concurrency_slot(user: dict, kind: str = "ask"):
    """Hold a per-user concurrency slot for the duration of an uncached AI read.

    Raises 429 if the user is already at ``ASK_MAX_CONCURRENT_PER_USER`` in-flight
    requests for this ``kind``. The slot is always released on exit — including when the
    wrapped provider work raises — so a failed request never leaves a slot stuck. Admins
    bypass the limit entirely.
    """
    if user.get("role") == "admin":
        yield
        return
    lock_id = await _acquire_slot(
        user["id"], kind,
        settings.ASK_MAX_CONCURRENT_PER_USER,
        settings.ASK_CONCURRENCY_TTL_SECONDS,
    )
    if lock_id is None:
        raise RateLimited(
            "You have too many AI requests running at once. Please wait for them to finish."
        )
    try:
        yield
    finally:
        try:
            await _release_slot(lock_id)
        except Exception:
            # Slot is self-expiring, so a failed release is not fatal — it just lingers
            # until expires_at. Never let cleanup mask the original outcome.
            pass
