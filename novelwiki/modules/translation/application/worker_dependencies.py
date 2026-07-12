"""Injected runtime capabilities for provider and AGY translation adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class ResumableRunPort(Protocol):
    async def list(self, job_id: int, workloads: tuple[str, ...]) -> list[dict]: ...


class TranslationQuotaPort(Protocol):
    async def reserve(self, user: dict, units: int = 1) -> bool: ...
    async def refund(self, user_id: int, units: int = 1) -> int: ...


RuntimeProvider = Callable[[], Awaitable[tuple[Any, Any]]]
GlossarySeeder = Callable[[int], Awaitable[int]]

_runtime_provider: RuntimeProvider | None = None
_glossary_seeder: GlossarySeeder | None = None
_runs: ResumableRunPort | None = None
_quota: TranslationQuotaPort | None = None


def configure_worker_dependencies(
    runtime_provider: RuntimeProvider,
    glossary_seeder: GlossarySeeder,
    runs: ResumableRunPort,
    quota: TranslationQuotaPort,
) -> None:
    global _runtime_provider, _glossary_seeder, _runs, _quota
    _runtime_provider = runtime_provider
    _glossary_seeder = glossary_seeder
    _runs = runs
    _quota = quota


async def translation_runtime() -> tuple[Any, Any]:
    if _runtime_provider is None:
        raise RuntimeError("Translation runtime was not wired by the composition root")
    return await _runtime_provider()


async def seed_glossary(novel_id: int) -> int:
    if _glossary_seeder is None:
        raise RuntimeError("Translation glossary seeder was not wired by the composition root")
    return await _glossary_seeder(novel_id)


def resumable_run_port() -> ResumableRunPort:
    if _runs is None:
        raise RuntimeError("Translation resumable-run port was not wired by the composition root")
    return _runs


def quota_port() -> TranslationQuotaPort:
    if _quota is None:
        raise RuntimeError("Translation quota port was not wired by the composition root")
    return _quota
