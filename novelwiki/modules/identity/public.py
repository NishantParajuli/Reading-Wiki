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
    def from_user(cls, user: Mapping[str, object]) -> "Principal":
        return cls(
            user_id=int(user["id"]),
            role=str(user.get("role") or "user"),
            status=str(user.get("status") or "active"),
            email_verified=bool(user.get("email_verified")),
            quota_limits=dict(user.get("quota_limits") or {}),
        )


@dataclass(frozen=True)
class SystemPrincipal:
    actor: str = "system"


class QuotaApi(Protocol):
    async def check_available(self, principal: Principal, kind: str, units: int = 1) -> None: ...
    async def reserve(self, principal: Principal, kind: str, units: int = 1) -> bool: ...
    async def refund(self, user_id: int, kind: str, units: int = 1) -> int: ...
