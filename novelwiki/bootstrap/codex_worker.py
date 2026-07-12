"""Composition wiring for Codex ingestion and dedicated-worker ports."""

from __future__ import annotations


def wire_codex_worker_dependencies() -> None:
    from novelwiki.modules.codex.application.worker_dependencies import (
        configure_worker_dependencies,
    )

    class ReadingBridge:
        @staticmethod
        async def _gateway():
            from novelwiki.modules.reading.adapters.outbound.codex import (
                PostgresReadingCodexGateway,
            )
            from novelwiki.platform.database import init_db_pool
            return PostgresReadingCodexGateway(await init_db_pool())

        async def chapter_numbers(self, novel_id, from_chapter=None, to_chapter=None, include_all=False):
            return await (await self._gateway()).chapter_numbers(
                novel_id, from_chapter, to_chapter, include_all
            )

        async def chapter_snapshot(self, novel_id, chapter_number):
            return await (await self._gateway()).chapter_snapshot(novel_id, chapter_number)

        async def locked_chapter_snapshot(self, connection, novel_id, chapter_number):
            from novelwiki.modules.reading.adapters.outbound.codex import (
                PostgresReadingCodexTransactionService,
            )
            return await PostgresReadingCodexTransactionService(
                connection
            ).locked_chapter_snapshot(novel_id, chapter_number)

    class RunBridge:
        async def list(self, job_id, workloads):
            from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
                PostgresAgyWorkerStateRepository,
            )
            from novelwiki.platform.database import init_db_pool
            return await PostgresAgyWorkerStateRepository(
                await init_db_pool()
            ).resumable_runs(job_id, workloads)

    configure_worker_dependencies(ReadingBridge(), RunBridge())

    from types import SimpleNamespace
    from novelwiki.modules.codex.application.ai_runtime import configure_ai_runtime
    from novelwiki.modules.ai_execution.adapters.outbound import providers
    from novelwiki.modules.ai_execution.adapters.outbound.agy.runner import run_agy
    from novelwiki.modules.ai_execution.adapters.outbound.agy.runs import (
        create_run, update_run, workspace_relpath,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.agy.validators import (
        load_json, read_text_artifact, validate_output_manifest,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import (
        add_input, create_run_workspace, seal_inputs, sha256_file, write_json,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import (
        is_database_error, safe_error_summary,
    )
    from novelwiki.modules.work.adapters.outbound import postgres as work

    configure_ai_runtime(SimpleNamespace(
        call_chat_completion=providers.call_chat_completion,
        get_embedding=providers.get_embedding,
        get_embeddings_batch=providers.get_embeddings_batch,
        rerank_passages=providers.rerank_passages,
        run_agy=run_agy, create_run=create_run, update_run=update_run,
        workspace_relpath=workspace_relpath, load_json=load_json,
        read_text_artifact=read_text_artifact,
        validate_output_manifest=validate_output_manifest,
        add_input=add_input, create_run_workspace=create_run_workspace,
        seal_inputs=seal_inputs, sha256_file=sha256_file, write_json=write_json,
        is_database_error=is_database_error, safe_error_summary=safe_error_summary,
    ), work)
