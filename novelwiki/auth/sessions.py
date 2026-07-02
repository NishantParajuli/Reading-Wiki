"""Server-side session lifecycle + cookie helpers."""
import datetime as dt

from fastapi import Response

from novelwiki.config.settings import settings
from novelwiki.auth.tokens import new_token, hash_token


def set_csrf_cookie(response: Response, token: str | None = None) -> str:
    token = token or new_token()
    response.set_cookie(
        settings.CSRF_COOKIE,
        token,
        max_age=settings.SESSION_TTL_DAYS * 86400,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return token


async def create_session(conn, user_id: int, user_agent: str | None = None) -> str:
    """Create a session row and return the raw token (only its hash is stored)."""
    token = new_token()
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.SESSION_TTL_DAYS)
    await conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at, user_agent) VALUES ($1, $2, $3, $4);",
        hash_token(token), user_id, expires, (user_agent or "")[:400],
    )
    return token


async def revoke_session(conn, token: str) -> None:
    await conn.execute("DELETE FROM sessions WHERE token_hash = $1;", hash_token(token))


async def revoke_user_sessions(conn, user_id: int) -> None:
    await conn.execute("DELETE FROM sessions WHERE user_id = $1;", user_id)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.SESSION_COOKIE,
        token,
        max_age=settings.SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    set_csrf_cookie(response)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.SESSION_COOKIE, path="/")
    response.delete_cookie(settings.CSRF_COOKIE, path="/")
