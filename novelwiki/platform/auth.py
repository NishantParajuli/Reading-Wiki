"""Shared web-auth transport dependencies composed from Identity."""

from novelwiki.modules.identity.adapters.inbound.dependencies import (
    current_user,
    optional_user,
    require_admin,
    require_verified,
)
from novelwiki.modules.identity.adapters.outbound import rate_limit

__all__ = [
    "current_user", "optional_user", "rate_limit", "require_admin", "require_verified",
]
