"""Catalog dependency wiring shared by HTTP and temporary compatibility callables."""

from __future__ import annotations


async def build_catalog_migration_service():
    from novelwiki.kernel.errors import ValidationFailed
    from novelwiki.modules.acquisition.adapters.outbound.catalog_workflows import (
        AcquisitionFilesystemCleanup,
        PostgresAcquisitionTransactionService,
    )
    from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import (
        SafeFetchError,
        validate_source_start_url,
    )
    from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import (
        CatalogMigrationService,
        CatalogTransactionService,
    )
    from novelwiki.modules.catalog.public import CatalogTransactionApi
    from novelwiki.modules.identity.adapters.outbound.postgres_directory import (
        PostgresUserDirectory,
    )
    from novelwiki.modules.identity.public import UserDirectoryApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        CatalogTransactionApi: lambda connection: CatalogTransactionService(
            PostgresCatalogRepository(connection)
        ),
        AcquisitionTransactionApi: PostgresAcquisitionTransactionService,
        UserDirectoryApi: PostgresUserDirectory,
    }

    async def validate_source_url(url: str) -> str:
        try:
            return await validate_source_start_url(url)
        except SafeFetchError as exc:
            raise ValidationFailed(f"Unsafe source URL: {exc}") from exc

    return CatalogMigrationService(
        lambda: AsyncpgUnitOfWork(pool, factories),
        validate_source_url,
        AcquisitionFilesystemCleanup(),
    )
