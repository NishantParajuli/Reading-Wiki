from __future__ import annotations

from fastapi import Response

from novelwiki.modules.identity.adapters.outbound.tokens import new_token
from novelwiki.platform.config import settings


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
