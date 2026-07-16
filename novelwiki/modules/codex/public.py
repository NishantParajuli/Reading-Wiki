from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ChapterCeiling:
    value: float


class CodexArtifacts(Protocol):
    async def has_chapter_artifacts(self, novel_id: int, chapters: tuple[float, ...]) -> bool: ...
    async def invalidate_chapter_range(self, novel_id: int, start: float, end: float) -> None: ...


class CodexTransactionApi(Protocol):
    async def has_chapter_artifacts(
        self, novel_id: int, chapters: tuple[float, ...]
    ) -> bool: ...
    async def invalidate_chapter_range(
        self, novel_id: int, start: float, end: float
    ) -> None: ...


class CodexExtractionTransactionApi(Protocol):
    """Codex-owned half of the atomic Reading/Codex extraction commit."""

    async def commit_extraction(
        self, novel_id: int, chapter: float, data: dict, chapter_summary: str,
        *, chapter_snapshot: dict, expected_source_hash: str,
        resolved_refs: dict[str, int | None], roster_refs: dict[str, int],
        thread_refs: dict[str, int], memory_targets: list[dict],
        context_manifest: dict, context_sha256: str, context_token_count: int,
        run_id: Any | None, model_label: str | None, force: bool,
    ) -> dict: ...


@dataclass(frozen=True)
class EstablishedTerm:
    canonical_name: str
    entity_type: str


class EstablishedTermsApi(Protocol):
    async def list_established_terms(self, novel_id: int) -> list[EstablishedTerm]: ...


class GetCodexMeta(Protocol):
    async def meta(self, novel_id: int, principal: object) -> dict: ...


class Ask(Protocol):
    async def ask(
        self, novel_id: int, question: str, ceiling: ChapterCeiling
    ) -> dict: ...


class ResolveEntity(Protocol):
    async def resolve_entity(
        self, novel_id: int, name: str, ceiling: ChapterCeiling
    ) -> list[dict]: ...


class MergeEntities(Protocol):
    async def merge_entities(
        self, novel_id: int, keep_id: int, drop_id: int, principal: object
    ) -> dict: ...


class CodexRecapApi(Protocol):
    async def recap(
        self, novel_id: int, requested_ceiling: float | None, principal: object
    ) -> dict: ...
