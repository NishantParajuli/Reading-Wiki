"""Small, framework-free primitives shared by NovelWiki modules."""

from .errors import (
    ApplicationError,
    Conflict,
    Forbidden,
    JobAlreadyActive,
    NotFound,
    ProviderUnavailable,
    QuotaExceeded,
    ValidationFailed,
)
from .transactions import TransactionContext, UnitOfWork

__all__ = [
    "ApplicationError",
    "Conflict",
    "Forbidden",
    "JobAlreadyActive",
    "NotFound",
    "ProviderUnavailable",
    "QuotaExceeded",
    "TransactionContext",
    "UnitOfWork",
    "ValidationFailed",
]
