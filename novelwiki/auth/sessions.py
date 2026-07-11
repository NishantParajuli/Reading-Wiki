"""Passive compatibility exports for Identity session and cookie helpers."""

from novelwiki.modules.identity.adapters.inbound.cookies import (
    clear_session_cookie,
    set_csrf_cookie,
    set_session_cookie,
)
from novelwiki.modules.identity.adapters.outbound.postgres_sessions import (
    create_session,
    revoke_session,
    revoke_user_sessions,
)

__all__ = [
    "clear_session_cookie",
    "create_session",
    "revoke_session",
    "revoke_user_sessions",
    "set_csrf_cookie",
    "set_session_cookie",
]
