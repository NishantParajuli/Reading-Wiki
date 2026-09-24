from unittest.mock import AsyncMock

import pytest

from novelwiki.kernel.errors import Forbidden
from novelwiki.modules.identity.application.quota import QuotaService
from novelwiki.modules.identity.domain.policies import spend_allowed
from novelwiki.modules.identity.public import Principal


@pytest.mark.parametrize("status", ["suspended", "banned"])
@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.asyncio
async def test_inactive_accounts_cannot_spend_or_reserve_quota(status, role):
    repository = AsyncMock()
    service = QuotaService(repository)
    principal = Principal(
        user_id=7, role=role, status=status, email_verified=True,
        quota_limits={"tts_chapters": 100},
    )

    assert spend_allowed(principal) is False
    assert await service.reserve(principal, "tts_chapters") is False
    with pytest.raises(Forbidden, match="not active"):
        await service.check_available(principal, "tts_chapters")
    with pytest.raises(Forbidden, match="not active"):
        await service.check_and_reserve(principal, "tts_chapters")

    repository.bump.assert_not_awaited()
    repository.try_reserve.assert_not_awaited()
    repository.get_usage.assert_not_awaited()


@pytest.mark.parametrize(
    "role,verified,allowed",
    [("user", False, False), ("user", True, True), ("admin", False, True)],
)
@pytest.mark.asyncio
async def test_active_account_spending_retains_verification_and_admin_rules(
    role, verified, allowed,
):
    repository = AsyncMock()
    repository.try_reserve.return_value = True
    service = QuotaService(repository)
    principal = Principal(
        user_id=7, role=role, email_verified=verified,
        quota_limits={"tts_chapters": 100},
    )

    assert spend_allowed(principal) is allowed
    assert await service.reserve(principal, "tts_chapters") is allowed
    if role == "admin":
        repository.bump.assert_awaited_once()
        repository.try_reserve.assert_not_awaited()
    elif allowed:
        repository.try_reserve.assert_awaited_once()
        repository.bump.assert_not_awaited()
    else:
        repository.try_reserve.assert_not_awaited()
        repository.bump.assert_not_awaited()
