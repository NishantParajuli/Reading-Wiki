"""Passive compatibility exports for Identity user helpers."""

from novelwiki.modules.identity.adapters.inbound.presentation import (
    avatar_url,
    public_user,
    quota_limits,
    self_user,
    self_user_with_capabilities,
)
from novelwiki.modules.identity.adapters.outbound.postgres_users import unique_username
from novelwiki.modules.identity.domain.policies import normalize_username, valid_username

__all__ = [
    "avatar_url",
    "normalize_username",
    "public_user",
    "quota_limits",
    "self_user",
    "self_user_with_capabilities",
    "unique_username",
    "valid_username",
]
