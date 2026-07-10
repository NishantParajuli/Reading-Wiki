from __future__ import annotations


class AgyError(RuntimeError):
    code = "unknown"
    retryable = True

    def __init__(self, message: str = "", *, code: str | None = None, retryable: bool | None = None):
        super().__init__(message or code or self.code)
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable


class AgyPreflightError(AgyError):
    retryable = False


class AgyValidationError(AgyError):
    code = "agy_artifact_invalid"


class AgyCanceled(AgyError):
    code = "agy_canceled"
    retryable = False


PROVIDER_WAIT_CODES = {"agy_quota_likely_exhausted", "agy_provider_unavailable"}


def classify_failure(stderr: str, *, exit_code: int | None = None, timed_out: bool = False) -> str:
    if timed_out:
        return "agy_timeout"
    text = (stderr or "").lower()
    quota_markers = ("quota", "rate limit", "resource exhausted", "ai credits", "weekly limit")
    auth_markers = ("not authenticated", "sign in", "login required", "unauthorized")
    permission_markers = ("permission denied", "approval required", "not allowed by policy")
    provider_markers = ("service unavailable", "server error", "temporarily unavailable", "connection reset")
    if any(x in text for x in quota_markers):
        return "agy_quota_likely_exhausted"
    if any(x in text for x in auth_markers):
        return "agy_not_authenticated"
    if any(x in text for x in permission_markers):
        return "agy_permission_blocked"
    if any(x in text for x in provider_markers):
        return "agy_provider_unavailable"
    return "agy_nonzero_exit" if exit_code not in (None, 0) else "unknown"


def safe_error_summary(exc: BaseException) -> str:
    """Non-story-bearing database/log summary; raw details stay in private run logs."""
    return f"{getattr(exc, 'code', 'unknown')}: {type(exc).__name__}"


def is_database_error(exc: BaseException) -> bool:
    try:
        import asyncpg
        return isinstance(exc, (asyncpg.PostgresError, asyncpg.InterfaceError, ConnectionError))
    except ImportError:
        return isinstance(exc, ConnectionError)
