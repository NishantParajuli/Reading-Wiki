from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from novelwiki.kernel.transactions import UnitOfWork

from novelwiki.modules.identity.public import Principal

from ..public import ChapterCeiling
from .dto import ActiveCodexJob, BackendDecision, CeilingContext


class CeilingPort(Protocol):
    async def resolve(
        self, novel_id: int, principal: Principal, requested: float | None
    ) -> CeilingContext: ...


class CodexQueryPort(Protocol):
    async def stats(self, novel_id: int, ceiling: ChapterCeiling) -> dict: ...
    async def list_entities(
        self, novel_id: int, ceiling: ChapterCeiling,
        entity_type: str | None, name_query: str | None,
    ) -> list[dict]: ...
    async def resolve_entity(
        self, novel_id: int, name: str, ceiling: ChapterCeiling
    ) -> list[dict]: ...
    async def entity_profile(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> dict | None: ...
    async def relationships(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling,
        other_id: int | None = None,
    ) -> list[dict]: ...
    async def timeline(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> list[dict]: ...
    async def identities(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> list[dict]: ...
    async def cached_profile(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling
    ) -> str | None: ...
    async def save_profile(
        self, novel_id: int, entity_id: int, ceiling: ChapterCeiling,
        rendered_md: str, model: str, evidence_ids: dict,
    ) -> None: ...


class CodexAgentPort(Protocol):
    def query_hash(self, question: str) -> str: ...
    async def cached_answer(
        self, novel_id: int, query_hash: str, ceiling: ChapterCeiling
    ) -> dict | None: ...
    async def citations(
        self, novel_id: int, answer: str, ceiling: ChapterCeiling
    ) -> list[dict]: ...
    async def answer(
        self, novel_id: int, question: str, ceiling: ChapterCeiling
    ) -> dict: ...
    async def ensure_index(self, novel_id: int) -> None: ...
    async def synthesize_profile(
        self, profile: dict, relationships: list[dict], ceiling: ChapterCeiling,
        model: str,
    ) -> str: ...


class AiCostControlPort(Protocol):
    def require_spend_allowed(self, principal: Principal) -> None: ...
    def concurrency_slot(
        self, principal: Principal, kind: str
    ) -> AbstractAsyncContextManager[None]: ...
    async def consume_rate(self, principal: Principal, kind: str) -> None: ...


class CatalogEditPort(Protocol):
    async def require_editable(self, novel_id: int, principal: Principal) -> None: ...
    async def enable_codex(self, novel_id: int) -> None: ...


class BackendResolutionPort(Protocol):
    async def resolve(self, principal: Principal, requested: str) -> BackendDecision: ...


class CodexWorkPort(Protocol):
    async def find_active(self, idempotency_key: str) -> ActiveCodexJob | None: ...
    async def schedule(
        self, *, novel_id: int, user_id: int, options: dict,
        idempotency_key: str, decision: BackendDecision,
        max_attempts: int | None,
    ) -> tuple[int, bool]: ...


class CodexQuotaPort(Protocol):
    async def reserve(self, principal: Principal) -> None: ...
    async def refund(self, user_id: int) -> None: ...


class EntityMergePort(Protocol):
    async def merge(self, novel_id: int, keep_id: int, drop_id: int) -> None: ...


class CodexReadingPort(Protocol):
    async def chapter_numbers(
        self, novel_id: int, from_chapter: float | None = None,
        to_chapter: float | None = None, include_all: bool = False,
    ) -> list[float]: ...
    async def chapter_snapshot(self, novel_id: int, chapter_number: float) -> dict | None: ...


class ResumableAiRunPort(Protocol):
    async def list(self, job_id: int, workloads: tuple[str, ...]) -> list[dict]: ...
    async def job_run_ids(self, job_id: int, workloads: tuple[str, ...]) -> tuple[UUID, ...]: ...


@dataclass(frozen=True)
class CodexRuntime:
    """Explicit capabilities supplied to Codex command/worker instances."""

    reading: CodexReadingPort
    runs: ResumableAiRunPort
    ai: Any
    work: Any
    extraction_uow_factory: Callable[[], UnitOfWork]
