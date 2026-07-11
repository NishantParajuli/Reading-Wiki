"""Translation dependency wiring."""

from __future__ import annotations


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
    return TranslationSchedulingService(
        CatalogBridge(), PostgresReadingTranslationQuery(pool),
        BackendResolutionBridge(), TranslationWorkBridge(),
        TranslationQuotaBridge(quota), settings.AGY_MAX_ATTEMPTS,
    )


async def build_translation_runtime():
    """Compatibility runtime for provider-facing translation functions."""
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
