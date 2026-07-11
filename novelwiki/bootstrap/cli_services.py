from __future__ import annotations


async def create_system_novel(novel, source):
    from novelwiki.modules.acquisition.adapters.outbound.catalog_workflows import (
        PostgresAcquisitionTransactionService,
    )
    from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogTransactionService
    from novelwiki.modules.catalog.public import CatalogTransactionApi
    from novelwiki.modules.identity.public import SystemPrincipal
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool
    from novelwiki.workflows.create_novel_with_source import create_novel_with_source
    pool = await init_db_pool()
    factories = {
        CatalogTransactionApi: lambda connection: CatalogTransactionService(
            PostgresCatalogRepository(connection)
        ),
        AcquisitionTransactionApi: PostgresAcquisitionTransactionService,
    }
    return await create_novel_with_source(
        lambda: AsyncpgUnitOfWork(pool, factories), SystemPrincipal("cli"), novel, source
    )


async def create_system_novel_from_cli(
    *, title: str, adapter: str, start_url: str, language: str,
    is_raw: bool, chapter_offset: float, codex_enabled: bool,
):
    from novelwiki.modules.acquisition.public import SourceDraft
    from novelwiki.modules.catalog.public import NovelDraft
    return await create_system_novel(
        NovelDraft(
            title=title, codex_enabled=codex_enabled, original_language=language,
        ),
        SourceDraft(
            adapter=adapter, start_url=start_url, language=language,
            is_raw=is_raw, chapter_offset=chapter_offset,
        ),
    )


async def merge_codex_entities(novel_id: int, keep_id: int, drop_id: int) -> None:
    from novelwiki.modules.codex.adapters.outbound.postgres_queries import PostgresEntityMerger
    from novelwiki.platform.database import init_db_pool
    await PostgresEntityMerger(await init_db_pool()).merge(novel_id, keep_id, drop_id)


async def reset_database() -> None:
    from novelwiki.db.schema import ALL_TABLES, init_database
    from novelwiki.platform.database import init_db_pool
    pool = await init_db_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            for table in ALL_TABLES:
                await connection.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
    await init_database()
