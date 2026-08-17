"""Composition of explicit Codex execution capabilities."""

from __future__ import annotations


def build_codex_runtime(provider: str = "agy"):
    from types import SimpleNamespace

    from novelwiki.modules.ai_execution.adapters.outbound import providers
    from novelwiki.modules.ai_execution.adapters.outbound.agy.runs import (
        create_run, update_run, workspace_relpath as agy_workspace_relpath,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.agy.validators import (
        load_json, read_text_artifact, validate_output_manifest,
    )
    from novelwiki.platform.config import settings
    from pathlib import Path
    if provider == "openai_codex":
        from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.runner import (
            build_task_prompt, is_database_error, run_openai_codex, safe_error_summary,
        )
        from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.workspace import (
            add_input, create_run_workspace, seal_inputs, sha256_file,
            workspace_relpath, write_json,
        )
        run_subscription = run_openai_codex
        model_codex = settings.OPENAI_CODEX_MODEL_CODEX
        contract_version = settings.OPENAI_CODEX_CONTRACT_VERSION
        work_root = Path(settings.OPENAI_CODEX_WORK_DIR).expanduser().resolve(strict=False)
        separate_verify = settings.OPENAI_CODEX_SEPARATE_CODEX_VERIFY
        provider_label = "OpenAI Codex"
    else:
        from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import (
            is_database_error, safe_error_summary,
        )
        from novelwiki.modules.ai_execution.adapters.outbound.agy.prompts import build_task_prompt
        from novelwiki.modules.ai_execution.adapters.outbound.agy.runner import run_agy
        from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import (
            add_input, create_run_workspace, seal_inputs, sha256_file,
            write_json,
        )
        workspace_relpath = agy_workspace_relpath
        run_subscription = run_agy
        model_codex = settings.AGY_MODEL_CODEX
        contract_version = settings.AGY_PLUGIN_VERSION
        work_root = Path(settings.AGY_WORK_DIR).expanduser().resolve(strict=False)
        separate_verify = settings.AGY_SEPARATE_CODEX_VERIFY
        provider_label = "AGY"
    from novelwiki.modules.codex.application.ports import CodexRuntime
    from novelwiki.modules.work.adapters.outbound import postgres as work

    class ReadingBridge:
        @staticmethod
        async def _gateway():
            from novelwiki.modules.reading.adapters.outbound.codex import (
                PostgresReadingCodexGateway,
            )
            from novelwiki.platform.database import init_db_pool
            return PostgresReadingCodexGateway(await init_db_pool())

        async def chapter_numbers(
            self, novel_id, from_chapter=None, to_chapter=None,
            require_content=False, narrative_only=False,
        ):
            return await (await self._gateway()).chapter_numbers(
                novel_id, from_chapter, to_chapter, require_content, narrative_only
            )

        async def chapter_snapshot(self, novel_id, chapter_number):
            return await (await self._gateway()).chapter_snapshot(
                novel_id, chapter_number
            )

    class RunBridge:
        async def list(self, job_id, workloads):
            from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
                PostgresAgyWorkerStateRepository,
            )
            from novelwiki.platform.database import init_db_pool
            return await PostgresAgyWorkerStateRepository(
                await init_db_pool(), provider
            ).resumable_runs(job_id, workloads)

        async def job_run_ids(self, job_id, workloads):
            from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
                PostgresAgyWorkerStateRepository,
            )
            from novelwiki.platform.database import init_db_pool
            return await PostgresAgyWorkerStateRepository(
                await init_db_pool(), provider
            ).job_run_ids(job_id, workloads)

    from functools import partial

    ai = SimpleNamespace(
        call_chat_completion=providers.call_chat_completion,
        get_embedding=providers.get_embedding,
        get_embeddings_batch=providers.get_embeddings_batch,
        rerank_passages=providers.rerank_passages,
        run_agy=run_subscription,
        build_task_prompt=build_task_prompt,
        create_run=partial(create_run, backend=provider),
        update_run=partial(update_run, event_backend=provider),
        workspace_relpath=workspace_relpath,
        load_json=load_json,
        read_text_artifact=read_text_artifact,
        validate_output_manifest=validate_output_manifest,
        add_input=add_input,
        create_run_workspace=create_run_workspace,
        seal_inputs=seal_inputs,
        sha256_file=sha256_file,
        write_json=write_json,
        is_database_error=is_database_error,
        safe_error_summary=safe_error_summary,
        model_codex=model_codex, model_label=f"{provider}:{model_codex}",
        contract_version=contract_version, work_root=work_root,
        separate_codex_verify=separate_verify, provider=provider,
        provider_label=provider_label,
    )

    runtime = None

    def uow_factory():
        from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
            PostgresCodexExtractionTransactionService,
        )
        from novelwiki.modules.codex.public import CodexExtractionTransactionApi
        from novelwiki.modules.reading.adapters.outbound.codex import (
            PostgresReadingCodexTransactionService,
        )
        from novelwiki.modules.reading.public import ReadingCodexTransactionApi
        from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

        class LazyUnitOfWork:
            async def __aenter__(self):
                pool = await init_db_pool()
                self._delegate = AsyncpgUnitOfWork(pool, {
                    ReadingCodexTransactionApi: PostgresReadingCodexTransactionService,
                    CodexExtractionTransactionApi: lambda connection: (
                        PostgresCodexExtractionTransactionService(connection, runtime)
                    ),
                })
                return await self._delegate.__aenter__()

            async def __aexit__(self, exc_type, exc, traceback):
                return await self._delegate.__aexit__(exc_type, exc, traceback)

        return LazyUnitOfWork()

    runtime = CodexRuntime(
        reading=ReadingBridge(), runs=RunBridge(), ai=ai, work=work,
        extraction_uow_factory=uow_factory,
    )
    return runtime


def wire_codex_worker_dependencies():
    """Stable bootstrap wrapper; returns dependencies instead of mutating globals."""
    return build_codex_runtime()
