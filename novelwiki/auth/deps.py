"""FastAPI dependencies that resolve the current user from the session cookie.

Usage in routes:
    user = Depends(current_user)     # 401 if not logged in
    user = Depends(optional_user)    # None if not logged in (public/discover surfaces)
    admin = Depends(require_admin)   # 403 if not an admin
"""
from fastapi import Depends, HTTPException, Request

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.tokens import hash_token


async def _load_user_by_token(token: str) -> dict | None:
    pool = await get_db_pool()
    th = hash_token(token)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.* FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = $1 AND s.expires_at > now() AND u.status = 'active';
            """,
            th,
        )
        if row is not None:
            await conn.execute("UPDATE sessions SET last_seen_at = now() WHERE token_hash = $1;", th)
    return dict(row) if row is not None else None


async def optional_user(request: Request) -> dict | None:
    token = request.cookies.get(settings.SESSION_COOKIE)
    if not token:
        return None
    return await _load_user_by_token(token)


async def current_user(request: Request) -> dict:
    user = await optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


async def require_verified(user: dict = Depends(current_user)) -> dict:
    """Gate actions that cost API money behind a verified email."""
    if not user.get("email_verified"):
        raise HTTPException(status_code=403, detail="Verify your email to use this feature.")
    return user


async def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    return user
