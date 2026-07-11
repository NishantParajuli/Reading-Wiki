"""Passive compatibility exports for Identity user helpers."""

from novelwiki.modules.identity.adapters.inbound.presentation import (
    avatar_url,
    public_user,
    quota_limits,
    self_user,
    self_user_with_capabilities as _self_user_with_capabilities,
)
from novelwiki.modules.identity.adapters.outbound.postgres_users import unique_username
from novelwiki.modules.identity.domain.policies import normalize_username, valid_username


async def self_user_with_capabilities(user: dict) -> dict:
    """Preserve the legacy helper while module adapters use explicit injection."""
    from novelwiki.modules.ai_execution.adapters.outbound.policy import capability_for_user

    return await _self_user_with_capabilities(user, capability_for_user)

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
