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
