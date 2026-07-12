"""Translation dependency wiring."""

from __future__ import annotations


def wire_translation_worker_dependencies() -> None:
    from novelwiki.modules.translation.application.worker_dependencies import (
        configure_worker_dependencies,
    )

    class RunBridge:
        async def list(self, job_id, workloads):
            from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
                PostgresAgyWorkerStateRepository,
            )
            from novelwiki.platform.database import init_db_pool
            return await PostgresAgyWorkerStateRepository(
                await init_db_pool()
            ).resumable_runs(job_id, workloads)

    class QuotaBridge:
        @staticmethod
        async def _service():
            from novelwiki.modules.identity.adapters.outbound.postgres_quota import PostgresQuotaRepository
            from novelwiki.modules.identity.application import QuotaService
            from novelwiki.platform.database import init_db_pool
            pool = await init_db_pool()
            return QuotaService(PostgresQuotaRepository(pool=pool))

        async def reserve(self, user, units=1):
            from novelwiki.modules.identity.adapters.principals import principal_from_user
            return await (await self._service()).reserve(
                principal_from_user(user), "translated_chapters", units
            )

        async def refund(self, user_id, units=1):
            return await (await self._service()).refund(
                user_id, "translated_chapters", units
            )

    configure_worker_dependencies(
        build_translation_runtime, seed_system_glossary, RunBridge(), QuotaBridge()
    )
    from types import SimpleNamespace
    from novelwiki.modules.translation.application.ai_runtime import configure_ai_runtime
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
        run_agy=run_agy, create_run=create_run, update_run=update_run,
        workspace_relpath=workspace_relpath, load_json=load_json,
        read_text_artifact=read_text_artifact,
        validate_output_manifest=validate_output_manifest,
        add_input=add_input, create_run_workspace=create_run_workspace,
        seal_inputs=seal_inputs, sha256_file=sha256_file, write_json=write_json,
        is_database_error=is_database_error, safe_error_summary=safe_error_summary,
    ), work)


async def build_glossary_service():
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogTransactionService
    from novelwiki.modules.catalog.public import CatalogTransactionApi
    from novelwiki.modules.codex.adapters.outbound.postgres_terms import PostgresEstablishedTerms
    from novelwiki.modules.codex.public import EstablishedTermsApi
    from novelwiki.modules.translation.adapters.outbound.postgres import (
        PostgresTranslationTransactionService,
    )
    from novelwiki.modules.translation.application import GlossaryService
    from novelwiki.modules.translation.public import TranslationTransactionApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        CatalogTransactionApi: lambda connection: CatalogTransactionService(
            PostgresCatalogRepository(connection)
        ),
        EstablishedTermsApi: PostgresEstablishedTerms,
        TranslationTransactionApi: PostgresTranslationTransactionService,
    }
    return GlossaryService(lambda: AsyncpgUnitOfWork(pool, factories))


async def build_translation_scheduling_service():
    from novelwiki.bootstrap.ai_execution import wire_ai_policy
    wire_ai_policy()
    wire_translation_worker_dependencies()
    from novelwiki.modules.ai_execution.adapters.outbound.policy import get_policy, resolve_backend
    from novelwiki.modules.ai_execution.domain.backend import Workload
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import PostgresQuotaRepository
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.reading.adapters.outbound.translation import PostgresReadingTranslationQuery
    from novelwiki.modules.translation.adapters.outbound.scheduling import (
        BackendResolutionBridge,
        TranslationQuotaBridge,
        TranslationWorkBridge,
    )
    from novelwiki.modules.translation.application import TranslationSchedulingService
    from novelwiki.modules.work.adapters.outbound import postgres as work_service
    from novelwiki.platform.config import settings
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()

    class CatalogBridge:
        async def require_editable(self, novel_id, principal):
            async with pool.acquire() as connection:
                await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_editable(novel_id, principal)

    quota = QuotaService(PostgresQuotaRepository(pool=pool))

    class WorkRuntime:
        ActiveJobLimitError = work_service.ActiveJobLimitError
        BackendPolicyChangedError = work_service.BackendPolicyChangedError
        find_active = staticmethod(work_service.find_active)
        job_view = staticmethod(work_service.job_view)

        @staticmethod
        async def create_job(*args, **kwargs):
            return await work_service.create_job(
                *args, **kwargs, policy_lookup=get_policy
            )

    return TranslationSchedulingService(
        CatalogBridge(), PostgresReadingTranslationQuery(pool),
        BackendResolutionBridge(resolve_backend, Workload.TRANSLATE_BATCH),
        TranslationWorkBridge(
            WorkRuntime(),
            work_service.ActiveJobLimitError,
            work_service.BackendPolicyChangedError,
        ),
        TranslationQuotaBridge(quota), settings.AGY_MAX_ATTEMPTS,
    )


async def build_translation_runtime():
    """Compatibility runtime for provider-facing translation functions."""
    wire_translation_worker_dependencies()
    from novelwiki.modules.reading.adapters.outbound.translation import (
        PostgresReadingTranslationQuery,
        PostgresReadingTranslationTransactionService,
    )
    from novelwiki.modules.reading.public import ReadingTranslationTransactionApi
    from novelwiki.modules.translation.adapters.outbound.postgres import (
        PostgresTranslationTransactionService,
    )
    from novelwiki.modules.translation.public import TranslationTransactionApi
    from novelwiki.modules.work.adapters.outbound.transactions import (
        PostgresWorkTransactionService,
    )
    from novelwiki.modules.work.public import WorkTransactionApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        ReadingTranslationTransactionApi: PostgresReadingTranslationTransactionService,
        TranslationTransactionApi: PostgresTranslationTransactionService,
        WorkTransactionApi: PostgresWorkTransactionService,
    }
    return PostgresReadingTranslationQuery(pool), lambda: AsyncpgUnitOfWork(pool, factories)


async def seed_system_glossary(novel_id: int) -> int:
    """Trusted CLI/worker seed preserving the historical system-principal semantics."""
    from novelwiki.modules.codex.adapters.outbound.postgres_terms import PostgresEstablishedTerms
    from novelwiki.modules.codex.public import EstablishedTermsApi
    from novelwiki.modules.translation.adapters.outbound.postgres import (
        PostgresTranslationTransactionService,
    )
    from novelwiki.modules.translation.public import TranslationTransactionApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        EstablishedTermsApi: PostgresEstablishedTerms,
        TranslationTransactionApi: PostgresTranslationTransactionService,
    }
    async with AsyncpgUnitOfWork(pool, factories) as uow:
        terms = await uow.transaction.bind(EstablishedTermsApi).list_established_terms(
            novel_id
        )
        return await uow.transaction.bind(
            TranslationTransactionApi
        ).seed_established_terms(novel_id, terms)
