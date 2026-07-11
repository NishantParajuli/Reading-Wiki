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
    from novelwiki.modules.reading.public import ReadingTransactionApi
    from novelwiki.modules.translation.adapters.outbound.legacy import (
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

    class LegacyChapterTranslationAdapter:
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
        LegacyChapterTranslationAdapter(),
        quota,
        settings.TRANSLATE_PREFETCH,
    )
