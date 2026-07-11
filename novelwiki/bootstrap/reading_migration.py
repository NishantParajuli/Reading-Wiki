"""Reading dependency wiring for chapters, overlays, and contributions."""

from __future__ import annotations


async def build_reading_migration_service():
    from novelwiki.modules.catalog.adapters.outbound.postgres import (
        PostgresCatalogRepository,
    )
    from novelwiki.modules.catalog.application import CatalogTransactionService
    from novelwiki.modules.catalog.public import CatalogTransactionApi
    from novelwiki.modules.identity.adapters.outbound.postgres_directory import (
        PostgresUserDirectory,
    )
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
        PostgresQuotaRepository,
    )
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.identity.public import Principal, UserDirectoryApi
    from novelwiki.modules.reading.adapters.outbound.postgres import (
        PostgresReadingRepository,
    )
    from novelwiki.modules.reading.application.migration import ReadingMigrationService
    from novelwiki.modules.reading.application.ports import SourceMetadataPort
    from novelwiki.modules.acquisition.adapters.outbound.catalog_workflows import (
        PostgresAcquisitionTransactionService,
    )
    from novelwiki.modules.reading.public import ReadingTransactionApi
    from novelwiki.modules.translation.adapters.outbound.runtime import (
        prefetch_translations,
        translate_chapter,
        translate_raw_text,
    )
    from novelwiki.platform.config import settings
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        CatalogTransactionApi: lambda connection: CatalogTransactionService(
            PostgresCatalogRepository(connection)
        ),
        ReadingTransactionApi: PostgresReadingRepository,
        UserDirectoryApi: PostgresUserDirectory,
        SourceMetadataPort: PostgresAcquisitionTransactionService,
    }

    def user_mapping(principal: Principal) -> dict:
        result = {
            "id": principal.user_id,
            "role": principal.role,
            "status": principal.status,
            "email_verified": principal.email_verified,
        }
        for kind, limit in principal.quota_limits.items():
            result[f"quota_{kind}"] = limit
        return result

    class ChapterTranslationGateway:
        async def translate_chapter(self, novel_id, number, principal):
            return await translate_chapter(
                novel_id, number,
                meter_user=(user_mapping(principal) if principal is not None else None),
            )

        async def translate_raw_chapter(self, novel_id, number):
            return await translate_raw_text(novel_id, number)

        async def prefetch(self, novel_id, after_number, count, principal):
            await prefetch_translations(
                novel_id, after_number, count,
                user_mapping(principal) if principal is not None else None,
            )

    quota = QuotaService(PostgresQuotaRepository(pool=pool))
    return ReadingMigrationService(
        lambda: AsyncpgUnitOfWork(pool, factories),
        ChapterTranslationGateway(),
        quota,
        settings.TRANSLATE_PREFETCH,
    )


async def build_reading_ingestion_gateway():
    from novelwiki.modules.reading.adapters.outbound.ingestion import (
        PostgresReadingIngestionGateway,
    )
    from novelwiki.platform.database import init_db_pool
    return PostgresReadingIngestionGateway(await init_db_pool())


async def build_reading_narration_gateway():
    from novelwiki.modules.reading.adapters.outbound.narration import (
        PostgresReadingNarrationGateway,
    )
    from novelwiki.platform.database import init_db_pool
    return PostgresReadingNarrationGateway(await init_db_pool())


async def build_reading_codex_gateway():
    from novelwiki.modules.reading.adapters.outbound.codex import PostgresReadingCodexGateway
    from novelwiki.platform.database import init_db_pool
    return PostgresReadingCodexGateway(await init_db_pool())


def bind_reading_codex(connection):
    from novelwiki.modules.reading.adapters.outbound.codex import (
        PostgresReadingCodexTransactionService,
    )
    return PostgresReadingCodexTransactionService(connection)
