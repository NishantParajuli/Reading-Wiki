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


class QuotaExceeded(ApplicationError):
    pass


class ProviderUnavailable(ApplicationError):
    pass


class JobAlreadyActive(Conflict):
    pass
