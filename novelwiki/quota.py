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

KINDS = ("translated_chapters", "ocr_pages", "codex_builds")


def _period() -> dt.date:
    return dt.date.today().replace(day=1)


def is_exempt(user: dict) -> bool:
    return user.get("role") == "admin"


async def get_usage(user_id: int) -> dict:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT translated_chapters, ocr_pages, codex_builds FROM quota_usage "
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
    if is_exempt(user):
        return None
    used = (await get_usage(user["id"]))[kind]
    return max(0, quota_limits(user)[kind] - used)


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
    if not user.get("email_verified"):
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


async def check_and_reserve(user: dict, kind: str, n: int = 1) -> None:
    """try_reserve, but raise the right HTTP error instead of returning False."""
    if not is_exempt(user) and not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Verify your email to use translation, OCR, or codex features.")
    if not await try_reserve(user, kind, n):
        limit = quota_limits(user)[kind]
        label = kind.replace("_", " ")
        raise HTTPException(
            status_code=429,
            detail=f"Monthly quota reached for {label} ({limit}/mo). Ask an admin to raise your limit.",
        )
