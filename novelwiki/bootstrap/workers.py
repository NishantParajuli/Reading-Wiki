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
    from novelwiki.modules.codex.adapters.outbound.ingest.chunk import chunk_all_chapters as _chunk
    from novelwiki.modules.codex.adapters.outbound.ingest.embed import embed_missing_chunks as _embed
    from novelwiki.modules.codex.adapters.outbound.ingest.extract import extract_all_chapters as _extract
    from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import get_bm25_manager

    async def codex(job, context):
        class CodexContext:
            bail_if_canceled = staticmethod(context.bail_if_canceled)
            chunk_all_chapters = staticmethod(_chunk)
            embed_missing_chunks = staticmethod(_embed)
            extract_all_chapters = staticmethod(_extract)
            set_progress = staticmethod(context.set_progress)

            @staticmethod
            async def rebuild_bm25(novel_id):
                await get_bm25_manager(novel_id).rebuild()

        return await execute_codex_job(job, CodexContext())

    registry = WorkerRegistry()
    registry.register("scrape", execute_scrape_job)
    registry.register("codex_build", codex)
    registry.register("translate", execute_translation_job)
    return registry


def build_agy_worker_registry() -> WorkerRegistry:
    from novelwiki.modules.translation.adapters.outbound.agy import execute_translation_job
    from novelwiki.modules.codex.adapters.inbound.jobs import execute_agy_codex_job
    from novelwiki.modules.codex.adapters.outbound.agy import (
        execute_codex_job as execute_codex_extraction,
    )
    from novelwiki.modules.codex.adapters.outbound.ingest.chunk import chunk_all_chapters as _chunk
    from novelwiki.modules.codex.adapters.outbound.ingest.embed import embed_missing_chunks as _embed
    from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import get_bm25_manager

    async def translation(job, preflight, _context):
        return await execute_translation_job(job, preflight)

    async def smoke(job, _preflight, _context):
        from novelwiki.modules.ai_execution.adapters.outbound.agy.smoke import run_smoke_test
        return await run_smoke_test(int(job["id"]))

    async def codex(job, preflight, context):
        class CodexContext:
            bail_if_canceled = staticmethod(context.bail_if_canceled)
            chunk_all_chapters = staticmethod(_chunk)
            embed_missing_chunks = staticmethod(_embed)
            set_progress = staticmethod(context.set_progress)
            execute_codex_job = staticmethod(
                getattr(context, "execute_codex_job", execute_codex_extraction)
            )

            @staticmethod
            async def rebuild_bm25(novel_id):
                await get_bm25_manager(novel_id).rebuild()

        return await execute_agy_codex_job(job, preflight, CodexContext())

    registry = WorkerRegistry()
    registry.register("translate", translation)
    registry.register("codex_build", codex)
    registry.register("agy_smoke", smoke)
    return registry
