"""Stable AI Execution DTOs, errors, enums, and capability protocols."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .application.contracts import (
    ArtifactRef, DisambiguationPayload, ExtractionPayload, InputManifest,
    MemoryUpdateProposal, OutputManifest, PlotThreadUpdateProposal, PreflightResult,
    RelationshipStateTransitionProposal, StateTransitionProposal, TranslationMeta,
)
from .application.errors import (
    AgyCanceled, AgyError, AgyPreflightError, AgyValidationError, BudgetExhausted,
    PROVIDER_WAIT_CODES,
)
from .domain.backend import ExecutionBackend, RequestedBackend, Workload


class ChatGateway(Protocol):
    async def complete(self, *, messages: list[dict], model: str, **options) -> object: ...


class EmbeddingGateway(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RerankGateway(Protocol):
    async def rerank(self, query: str, documents: list[str], top_n: int) -> object: ...


class VisionGateway(Protocol):
    async def inspect(self, images: list[bytes], prompt: str) -> object: ...


class ResumableRunQuery(Protocol):
    async def resumable_runs(self, job_id: int, workloads: tuple[str, ...]) -> list[dict]: ...
    async def job_run_ids(self, job_id: int, workloads: tuple[str, ...]) -> tuple[UUID, ...]: ...


__all__ = [
    "AgyCanceled", "AgyError", "AgyPreflightError", "AgyValidationError", "BudgetExhausted",
    "ArtifactRef", "ChatGateway", "DisambiguationPayload", "EmbeddingGateway",
    "ExecutionBackend", "ExtractionPayload", "InputManifest", "MemoryUpdateProposal",
    "OutputManifest", "PlotThreadUpdateProposal", "PreflightResult",
    "PROVIDER_WAIT_CODES", "RequestedBackend", "RerankGateway", "ResumableRunQuery",
    "RelationshipStateTransitionProposal", "StateTransitionProposal", "TranslationMeta",
    "VisionGateway", "Workload",
]
