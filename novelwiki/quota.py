"""Per-user monthly spend metering.

The platform is open-registration, so anything that costs API money (translation, OCR,
codex builds) is metered per user per calendar month. Admins are unlimited; everyone else
is capped by their per-user override (users.quota_*) or the settings default, and must have
a verified email to spend at all.

`kind` is one of KINDS; it's interpolated into SQL, so it is validated against that set
(never user-supplied free text).
"""
import datetime as dt

from fastapi import HTTPException

from novelwiki.db.connection import get_db_pool
from novelwiki.auth.users import quota_limits

KINDS = ("translated_chapters", "ocr_pages", "codex_builds", "tts_chapters")


def _period() -> dt.date:
    return dt.date.today().replace(day=1)


def is_exempt(user: dict) -> bool:
    return user.get("role") == "admin"


def spend_allowed(user: dict) -> bool:
    """Whether this account may trigger API-costing work at all."""
    return is_exempt(user) or bool(user.get("email_verified"))


def require_spend_allowed(user: dict) -> None:
    if not spend_allowed(user):
        raise HTTPException(status_code=403, detail="Verify your email to use scrape, translation, OCR, codex, or import features.")


async def get_usage(user_id: int) -> dict:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT translated_chapters, ocr_pages, codex_builds, tts_chapters FROM quota_usage "
            "WHERE user_id = $1 AND period = $2;",
            user_id, _period(),
        )
    return {k: (int(row[k]) if row else 0) for k in KINDS}


async def usage_and_limits(user: dict) -> dict:
    used = await get_usage(user["id"])
    limits = quota_limits(user)
    return {
        "period": _period().isoformat(),
        "unlimited": is_exempt(user),
        "usage": used,
        "limits": limits,
        "remaining": {k: (None if is_exempt(user) else max(0, limits[k] - used[k])) for k in KINDS},
    }


async def _bump(user_id: int, kind: str, n: int) -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO quota_usage (user_id, period) VALUES ($1, $2) ON CONFLICT DO NOTHING;",
            user_id, _period(),
        )
        await conn.execute(
            f"UPDATE quota_usage SET {kind} = {kind} + $3 WHERE user_id = $1 AND period = $2;",
            user_id, _period(), n,
        )


async def remaining(user: dict, kind: str) -> int | None:
    """Units left this month, or None for unlimited (admin)."""
    if kind not in KINDS:
        raise ValueError(f"unknown quota kind: {kind}")
    if is_exempt(user):
        return None
    used = (await get_usage(user["id"]))[kind]
    return max(0, quota_limits(user)[kind] - used)


async def check_available(user: dict, kind: str, n: int = 1) -> None:
    """Preflight a spend without reserving it. Actual workers should still call
    try_reserve close to the work, because this check is intentionally non-locking."""
    if kind not in KINDS:
        raise ValueError(f"unknown quota kind: {kind}")
    require_spend_allowed(user)
    if n <= 0 or is_exempt(user):
        return
    limit = quota_limits(user)[kind]
    used = (await get_usage(user["id"]))[kind]
    if used + n > limit:
        label = kind.replace("_", " ")
        raise HTTPException(
            status_code=429,
            detail=f"Monthly quota reached for {label} ({limit}/mo). Ask an admin to raise your limit.",
        )


async def try_reserve(user: dict, kind: str, n: int = 1) -> bool:
    """Atomically reserve `n` units. Returns False (reserving nothing) if it would exceed the
    cap or the email isn't verified. Admins always succeed (usage still tracked for analytics)."""
    if kind not in KINDS:
        raise ValueError(f"unknown quota kind: {kind}")
    if n <= 0:
        return True
    if is_exempt(user):
        await _bump(user["id"], kind, n)
        return True
    if not spend_allowed(user):
        return False
    limit = quota_limits(user)[kind]
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO quota_usage (user_id, period) VALUES ($1, $2) ON CONFLICT DO NOTHING;",
                user["id"], _period(),
            )
            used = await conn.fetchval(
                f"SELECT {kind} FROM quota_usage WHERE user_id = $1 AND period = $2 FOR UPDATE;",
                user["id"], _period(),
            )
            if used + n > limit:
                return False
            await conn.execute(
                f"UPDATE quota_usage SET {kind} = {kind} + $3 WHERE user_id = $1 AND period = $2;",
                user["id"], _period(), n,
            )
    return True


async def refund(user_id: int, kind: str, n: int = 1) -> int:
    """Return up to `n` reserved units for the current month to a user, clamping so recorded
    usage never drops below zero. Returns how many were actually refunded.

    Used by durable-job finalizers when reserved API budget wasn't consumed (a build that
    crashed, hit a provider failure, or was cancelled before doing the expensive work). Takes a
    `user_id` (not a user dict) because the finalizer runs from the worker off a stored job row,
    and refunds admins too (their usage is tracked for analytics, so it must be corrected as well)."""
    if kind not in KINDS:
        raise ValueError(f"unknown quota kind: {kind}")
    if user_id is None or n <= 0:
        return 0
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            used = await conn.fetchval(
                f"SELECT {kind} FROM quota_usage WHERE user_id = $1 AND period = $2 FOR UPDATE;",
                user_id, _period(),
            )
            if used is None:
                return 0
            give = min(int(n), int(used))
            if give <= 0:
                return 0
            await conn.execute(
                f"UPDATE quota_usage SET {kind} = {kind} - $3 WHERE user_id = $1 AND period = $2;",
                user_id, _period(), give,
            )
    return give


async def check_and_reserve(user: dict, kind: str, n: int = 1) -> None:
    """try_reserve, but raise the right HTTP error instead of returning False."""
    require_spend_allowed(user)
    if not await try_reserve(user, kind, n):
        limit = quota_limits(user)[kind]
        label = kind.replace("_", " ")
        raise HTTPException(
            status_code=429,
            detail=f"Monthly quota reached for {label} ({limit}/mo). Ask an admin to raise your limit.",
        )
