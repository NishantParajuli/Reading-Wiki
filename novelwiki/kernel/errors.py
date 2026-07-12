"""Errors that cross application boundaries without depending on a transport."""


class ApplicationError(Exception):
    """Base class for expected domain/application failures."""


class NotFound(ApplicationError):
    pass


class Forbidden(ApplicationError):
    pass


class Conflict(ApplicationError):
    pass


class ValidationFailed(ApplicationError):
    pass


class InvalidOperation(ApplicationError):
    """A valid request that is disallowed by the current operation context (HTTP 400)."""

    pass


class QuotaExceeded(ApplicationError):
    pass


class ProviderUnavailable(ApplicationError):
    pass


class RateLimited(ApplicationError):
    def __init__(self, detail: str, *, retry_after: int | None = None):
        super().__init__(detail)
        self.retry_after = retry_after


class JobAlreadyActive(Conflict):
    pass
