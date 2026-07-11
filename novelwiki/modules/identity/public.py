from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


@dataclass(frozen=True)
class Principal:
    user_id: int
    role: str
    status: str = "active"
    email_verified: bool = False
    quota_limits: Mapping[str, int] = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def from_user(
        cls,
        user: Mapping[str, object],
        quota_defaults: Mapping[str, int] | None = None,
    ) -> "Principal":
        quota_limits = dict(user.get("quota_limits") or {})
        if quota_defaults is not None:
            for kind, default in quota_defaults.items():
                column = f"quota_{kind}"
                value = user.get(column)
                quota_limits[kind] = int(default if value is None else value)
        return cls(
            user_id=int(user["id"]),
            role=str(user.get("role") or "user"),
            status=str(user.get("status") or "active"),
            email_verified=bool(user.get("email_verified")),
            quota_limits=quota_limits,
        )


@dataclass(frozen=True)
class SystemPrincipal:
    actor: str = "system"


class QuotaApi(Protocol):
    async def check_available(self, principal: Principal, kind: str, units: int = 1) -> None: ...
    async def reserve(self, principal: Principal, kind: str, units: int = 1) -> bool: ...
    async def refund(self, user_id: int, kind: str, units: int = 1) -> int: ...


class IdentityQuotaTransactionApi(Protocol):
    async def refund(self, user_id: int, kind: str, units: int = 1) -> int: ...


def quota_transaction_factory(connection: object) -> IdentityQuotaTransactionApi:
    """Composition bridge for callers binding Identity to an existing transaction."""
    from .adapters.outbound.postgres_quota import PostgresQuotaTransactionService

    return PostgresQuotaTransactionService(connection)


@dataclass(frozen=True)
class UserLabel:
    user_id: int
    username: str
    display_name: str


class UserDirectoryApi(Protocol):
    async def labels(self, user_ids: set[int]) -> dict[int, UserLabel]: ...


class IdentityAdminTransactionApi(Protocol):
    async def user_role(self, user_id: int) -> str | None: ...
    async def other_admin_count(self, user_id: int) -> int: ...
    async def update_user(self, user_id: int, fields: Mapping[str, object]) -> None: ...
    async def revoke_sessions(self, user_id: int) -> None: ...
    async def delete_user(self, user_id: int) -> None: ...


class IdentityAdminApi(Protocol):
    async def update_user(
        self, user_id: int, fields: dict, administrator: Principal
    ) -> str: ...
    async def delete_user(self, user_id: int, administrator: Principal) -> None: ...


from .adapters.inbound.presentation import quota_limits  # noqa: E402


def is_exempt(user: dict) -> bool:
    from .adapters.outbound.quota_compat import is_exempt as implementation
    return implementation(user)


def spend_allowed(user: dict) -> bool:
    from .adapters.outbound.quota_compat import spend_allowed as implementation
    return implementation(user)


def require_spend_allowed(user: dict) -> None:
    from .adapters.outbound.quota_compat import require_spend_allowed as implementation
    implementation(user)


async def get_usage(user_id: int) -> dict:
    from .adapters.outbound.quota_compat import get_usage as implementation
    return await implementation(user_id)


async def usage_and_limits(user: dict) -> dict:
    from .adapters.outbound.quota_compat import usage_and_limits as implementation
    return await implementation(user)


async def remaining(user: dict, kind: str) -> int | None:
    from .adapters.outbound.quota_compat import remaining as implementation
    return await implementation(user, kind)


async def check_available(user: dict, kind: str, n: int = 1) -> None:
    from .adapters.outbound.quota_compat import check_available as implementation
    await implementation(user, kind, n)


async def try_reserve(user: dict, kind: str, n: int = 1) -> bool:
    from .adapters.outbound.quota_compat import try_reserve as implementation
    return await implementation(user, kind, n)


async def refund(user_id: int, kind: str, n: int = 1, *, conn=None) -> int:
    from .adapters.outbound.quota_compat import refund as implementation
    return await implementation(user_id, kind, n, conn=conn)


async def check_and_reserve(user: dict, kind: str, n: int = 1) -> None:
    from .adapters.outbound.quota_compat import check_and_reserve as implementation
    await implementation(user, kind, n)
