"""Explicit worker-handler registry assembled outside feature modules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

WorkerHandler = Callable[..., Awaitable[object]]


class WorkerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, WorkerHandler] = {}

    def register(self, workload: str, handler: WorkerHandler) -> None:
        if workload in self._handlers:
            raise ValueError(f"Worker handler already registered for {workload!r}")
        self._handlers[workload] = handler

    def resolve(self, workload: str) -> WorkerHandler:
        try:
            return self._handlers[workload]
        except KeyError as exc:
            raise LookupError(f"No worker handler registered for {workload!r}") from exc

    @property
    def workloads(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


def build_api_worker_registry() -> WorkerRegistry:
    from novelwiki.modules.acquisition.adapters.inbound.jobs import execute_scrape_job
    from novelwiki.modules.codex.adapters.inbound.jobs import execute_codex_job
    from novelwiki.modules.translation.adapters.inbound.jobs import execute_translation_job

    registry = WorkerRegistry()
    registry.register("scrape", execute_scrape_job)
    registry.register("codex_build", execute_codex_job)
    registry.register("translate", execute_translation_job)
    return registry


def build_agy_worker_registry() -> WorkerRegistry:
    from novelwiki.agy.translation import execute_translation_job
    from novelwiki.modules.codex.adapters.inbound.jobs import execute_agy_codex_job

    async def translation(job, preflight, _context):
        return await execute_translation_job(job, preflight)

    async def smoke(job, _preflight, _context):
        from novelwiki.agy.smoke import run_smoke_test
        return await run_smoke_test(int(job["id"]))

    registry = WorkerRegistry()
    registry.register("translate", translation)
    registry.register("codex_build", execute_agy_codex_job)
    registry.register("agy_smoke", smoke)
    return registry
