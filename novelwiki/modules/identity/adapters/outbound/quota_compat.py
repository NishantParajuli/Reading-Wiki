"""Compatibility facade for Identity's framework-independent quota service."""

from __future__ import annotations

from novelwiki.platform.database import get_db_pool
from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
    PostgresQuotaRepository,
)
from novelwiki.modules.identity.adapters.principals import principal_from_user
from novelwiki.modules.identity.application.quota import (
    QUOTA_KINDS,
    QuotaService,
    current_period,
)
from novelwiki.modules.identity.domain.policies import spend_allowed as _spend_allowed
from novelwiki.modules.identity.public import Principal

KINDS = QUOTA_KINDS


def _period():
    return current_period()


def _principal(user: dict) -> Principal:
    return principal_from_user(user)


async def _service(*, conn=None) -> QuotaService:
    repository = (
        PostgresQuotaRepository(connection=conn)
        if conn is not None
        else PostgresQuotaRepository(pool=await get_db_pool())
    )
    return QuotaService(repository)


def is_exempt(user: dict) -> bool:
    return _principal(user).is_admin


def spend_allowed(user: dict) -> bool:
    return _spend_allowed(_principal(user))


def require_spend_allowed(user: dict) -> None:
    QuotaService.require_spend_allowed(_principal(user))


async def get_usage(user_id: int) -> dict:
    return await (await _service()).get_usage(user_id)


async def usage_and_limits(user: dict) -> dict:
    return await (await _service()).usage_and_limits(_principal(user))


async def _bump(user_id: int, kind: str, n: int) -> None:
    service = await _service()
    service.validate_kind(kind)
    await service._repository.bump(user_id, current_period(), kind, n)


async def remaining(user: dict, kind: str) -> int | None:
    return await (await _service()).remaining(_principal(user), kind)


async def check_available(user: dict, kind: str, n: int = 1) -> None:
    await (await _service()).check_available(_principal(user), kind, n)


async def try_reserve(user: dict, kind: str, n: int = 1) -> bool:
    return await (await _service()).reserve(_principal(user), kind, n)


async def refund(user_id: int, kind: str, n: int = 1, *, conn=None) -> int:
    return await (await _service(conn=conn)).refund(user_id, kind, n)


async def check_and_reserve(user: dict, kind: str, n: int = 1) -> None:
    await (await _service()).check_and_reserve(_principal(user), kind, n)
