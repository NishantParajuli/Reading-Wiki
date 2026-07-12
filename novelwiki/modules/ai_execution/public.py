"""Stable AI Execution DTOs, errors, enums, and capability protocols."""

from __future__ import annotations

from typing import Protocol

from .application.contracts import (
    ArtifactRef, DisambiguationPayload, ExtractionPayload, InputManifest,
    OutputManifest, PreflightResult, TranslationMeta,
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


__all__ = [
    "AgyCanceled", "AgyError", "AgyPreflightError", "AgyValidationError", "BudgetExhausted",
    "ArtifactRef", "ChatGateway", "DisambiguationPayload", "EmbeddingGateway",
    "ExecutionBackend", "ExtractionPayload", "InputManifest", "OutputManifest", "PreflightResult",
    "PROVIDER_WAIT_CODES", "RequestedBackend", "RerankGateway", "ResumableRunQuery",
    "TranslationMeta", "VisionGateway", "Workload",
]
