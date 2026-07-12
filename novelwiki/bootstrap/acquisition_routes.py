"""Composition builder for native Acquisition HTTP routes."""

from __future__ import annotations


async def build_acquisition_service():
    from novelwiki.bootstrap.acquisition_runtime import wire_acquisition_runtime
    wire_acquisition_runtime()
    from novelwiki.modules.work.adapters.outbound import postgres as jobs_service
    from novelwiki.modules.acquisition.adapters.outbound.assets import (
        AcquisitionAssetFilesystem,
    )
    from novelwiki.modules.acquisition.adapters.outbound.postgres import (
        PostgresAcquisitionRepository,
    )
    from novelwiki.modules.acquisition.adapters.outbound.scheduling import (
        DurableScrapeWorkAdapter,
        SafeSourceUrlAdapter,
    )
    from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import (
        validate_source_start_url,
    )
    from novelwiki.modules.acquisition.application import AcquisitionService
    from novelwiki.modules.acquisition.adapters.outbound.catalog_workflows import (
        PostgresAcquisitionTransactionService,
    )
    from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
    from novelwiki.modules.catalog.adapters.outbound.postgres import (
        PostgresCatalogRepository,
    )
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.codex.adapters.outbound.artifacts import (
        PostgresCodexTransactionService,
    )
    from novelwiki.modules.codex.public import CodexTransactionApi
    from novelwiki.modules.reading.adapters.outbound.postgres import (
        PostgresReadingRepository,
    )
    from novelwiki.modules.reading.public import ReadingTransactionApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool
    from novelwiki.workflows.update_source_offset import update_source_offset

    pool = await init_db_pool()

    class CatalogAccessBridge:
        async def require_readable(self, novel_id, principal):
            async with pool.acquire() as connection:
                await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_readable(novel_id, principal)

        async def require_editable(self, novel_id, principal):
            async with pool.acquire() as connection:
                await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_editable(novel_id, principal)

    class SpendPolicyBridge:
        def ensure_allowed(self, principal):
            QuotaService.require_spend_allowed(principal)

    factories = {
        AcquisitionTransactionApi: PostgresAcquisitionTransactionService,
        ReadingTransactionApi: PostgresReadingRepository,
        CodexTransactionApi: PostgresCodexTransactionService,
    }

    class SourceOffsetBridge:
        async def update(self, source_id, offset):
            return await update_source_offset(
                lambda: AsyncpgUnitOfWork(pool, factories), source_id, offset
            )

    return AcquisitionService(
        PostgresAcquisitionRepository(pool),
        CatalogAccessBridge(),
        SafeSourceUrlAdapter(validate_source_start_url),
        SpendPolicyBridge(),
        DurableScrapeWorkAdapter(jobs_service.create_job),
        AcquisitionAssetFilesystem(),
        SourceOffsetBridge(),
    )


def build_acquisition_routes():
    from novelwiki.modules.acquisition.adapters.inbound.http import router

    return router


async def build_import_service():
    from novelwiki.bootstrap.acquisition_runtime import wire_acquisition_runtime
    wire_acquisition_runtime()
    from novelwiki.platform.config import settings
    from novelwiki.modules.acquisition.adapters.outbound.import_gateway import (
        ImportRuntimeGateway,
    )
    from novelwiki.modules.acquisition.application import (
        ImportConfig, ImportService,
    )
    from novelwiki.modules.catalog.adapters.outbound.postgres import (
        PostgresCatalogRepository,
    )
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
        PostgresQuotaRepository,
    )
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()

    class CatalogAccessBridge:
        async def require_readable(self, novel_id, principal):
            async with pool.acquire() as connection:
                await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_readable(novel_id, principal)

        async def require_editable(self, novel_id, principal):
            async with pool.acquire() as connection:
                await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_editable(novel_id, principal)

    class SpendPolicyBridge:
        def __init__(self):
            self._quota = QuotaService(PostgresQuotaRepository(pool=pool))

        def ensure_allowed(self, principal):
            self._quota.require_spend_allowed(principal)

        async def reserve_ocr(self, principal, pages):
            await self._quota.check_and_reserve(principal, "ocr_pages", pages)

    return ImportService(
        ImportRuntimeGateway(pool), CatalogAccessBridge(), SpendPolicyBridge(),
        ImportConfig(
            incoming_dir=settings.IMPORT_INCOMING_DIR,
            max_upload_bytes=settings.MAX_UPLOAD_MB * 1024 * 1024,
            max_upload_mb=settings.MAX_UPLOAD_MB,
            max_chunked_bytes=settings.MAX_CHUNKED_UPLOAD_MB * 1024 * 1024,
            max_chunked_upload_mb=settings.MAX_CHUNKED_UPLOAD_MB,
        ),
    )


def build_acquisition_principal_factory():
    from novelwiki.modules.identity.adapters.principals import principal_from_user
    return principal_from_user


async def build_import_commit_uow_factory():
    from novelwiki.modules.acquisition.adapters.outbound.catalog_workflows import (
        PostgresAcquisitionTransactionService,
    )
    from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogTransactionService
    from novelwiki.modules.catalog.public import CatalogTransactionApi
    from novelwiki.modules.codex.adapters.outbound.artifacts import PostgresCodexTransactionService
    from novelwiki.modules.codex.public import CodexTransactionApi
    from novelwiki.modules.reading.adapters.outbound.ingestion import (
        PostgresReadingIngestionTransactionService,
    )
    from novelwiki.modules.reading.public import ReadingIngestionTransactionApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        AcquisitionTransactionApi: PostgresAcquisitionTransactionService,
        CatalogTransactionApi: lambda connection: CatalogTransactionService(
            PostgresCatalogRepository(connection)
        ),
        ReadingIngestionTransactionApi: PostgresReadingIngestionTransactionService,
        CodexTransactionApi: PostgresCodexTransactionService,
    }
    return lambda: AsyncpgUnitOfWork(pool, factories)


def bind_import_commit_apis(connection):
    from novelwiki.modules.acquisition.adapters.outbound.catalog_workflows import (
        PostgresAcquisitionTransactionService,
    )
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogTransactionService
    from novelwiki.modules.codex.adapters.outbound.artifacts import PostgresCodexTransactionService
    from novelwiki.modules.reading.adapters.outbound.ingestion import (
        PostgresReadingIngestionTransactionService,
    )
    from novelwiki.workflows.commit_import import ImportCommitApis
    return ImportCommitApis(
        acquisition=PostgresAcquisitionTransactionService(connection),
        catalog=CatalogTransactionService(PostgresCatalogRepository(connection)),
        reading=PostgresReadingIngestionTransactionService(connection),
        codex=PostgresCodexTransactionService(connection),
    )


async def reserve_auto_codex(user_id: int) -> bool:
    from novelwiki.modules.identity.adapters.outbound.worker_lookup import (
        PostgresIdentityWorkerLookup,
    )
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import PostgresQuotaRepository
    from novelwiki.modules.identity.adapters.principals import principal_from_user
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()
    user = await PostgresIdentityWorkerLookup(pool).load_user(user_id)
    return bool(
        user and await QuotaService(PostgresQuotaRepository(pool=pool)).reserve(
            principal_from_user(user), "codex_builds", 1
        )
    )
