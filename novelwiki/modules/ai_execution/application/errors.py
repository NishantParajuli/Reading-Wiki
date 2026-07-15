"""Errors exposed by AI Execution without adapter dependencies."""

from __future__ import annotations


class AgyError(RuntimeError):
    code = "unknown"
    retryable = True

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        retryable: bool | None = None,
        metrics: dict | None = None,
    ):
        super().__init__(message or code or self.code)
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.metrics = dict(metrics or {})


class AgyPreflightError(AgyError):
    retryable = False


class AgyValidationError(AgyError):
    code = "agy_artifact_invalid"


class AgyCanceled(AgyError):
    code = "agy_canceled"
    retryable = False


class BudgetExhausted(Exception):
    """The configured provider's durable daily budget is exhausted."""


PROVIDER_WAIT_CODES = {"agy_quota_likely_exhausted", "agy_provider_unavailable"}
