"""Adapter-specific AGY error classification helpers."""

from novelwiki.modules.ai_execution.application.errors import *  # noqa: F401,F403


def classify_failure(stderr: str, *, exit_code: int | None = None, timed_out: bool = False) -> str:
    if timed_out:
        return "agy_timeout"
    text = (stderr or "").lower()
    markers = {
        "agy_quota_likely_exhausted": ("quota", "rate limit", "resource exhausted", "ai credits", "weekly limit"),
        "agy_not_authenticated": ("not authenticated", "sign in", "login required", "unauthorized"),
        "agy_permission_blocked": ("permission denied", "approval required", "not allowed by policy"),
        "agy_provider_unavailable": ("service unavailable", "server error", "temporarily unavailable", "connection reset"),
    }
    for code, values in markers.items():
        if any(value in text for value in values):
            return code
    return "agy_nonzero_exit" if exit_code not in (None, 0) else "unknown"


def safe_error_summary(exc: BaseException) -> str:
    return f"{getattr(exc, 'code', 'unknown')}: {type(exc).__name__}"


def is_database_error(exc: BaseException) -> bool:
    try:
        import asyncpg
        return isinstance(exc, (asyncpg.PostgresError, asyncpg.InterfaceError, ConnectionError))
    except ImportError:
        return isinstance(exc, ConnectionError)
