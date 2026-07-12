from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from novelwiki.modules.identity.public import Principal


@dataclass(frozen=True)
class BackendDecision:
    requested: str
    resolved: str
    reason: str
    model: str | None
    policy_version: int | None
    fallback_allowed: bool


@dataclass(frozen=True)
class ActiveTranslationJob:
    job_id: int
    chapters: int
    execution_backend: str
    model: str | None


class CatalogAccessPort(Protocol):
    async def require_editable(self, novel_id: int, principal: Principal) -> None: ...


class ReadingTranslationPort(Protocol):
    async def count_pending(
        self, novel_id: int, from_chapter: float | None,
        to_chapter: float | None, force: bool,
    ) -> int: ...


class BackendResolutionPort(Protocol):
    async def resolve(self, principal: Principal, requested: str) -> BackendDecision: ...


class TranslationWorkPort(Protocol):
    async def find_active(self, idempotency_key: str) -> ActiveTranslationJob | None: ...
    async def schedule(
        self, *, novel_id: int, user_id: int, options: dict,
        idempotency_key: str, decision: BackendDecision,
        quota_reserved: int, max_attempts: int | None,
    ) -> tuple[int, bool]: ...


class TranslationQuotaPort(Protocol):
    async def check_available(self, principal: Principal, units: int) -> None: ...
    async def reserve(self, principal: Principal, units: int) -> None: ...
    async def refund(self, user_id: int, units: int) -> None: ...


@dataclass(frozen=True)
class TranslationRuntime:
    """Explicit capabilities supplied to Translation command/worker instances."""

    reading: Any
    uow_factory: Callable[[], Any]
    seed_glossary: Callable[[int], Awaitable[int]]
    runs: Any
    quota: Any
    ai: Any
    work: Any
