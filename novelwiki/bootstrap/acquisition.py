from novelwiki.modules.acquisition.adapters.outbound.adapter_catalog import (
    BuiltinScraperAdapterCatalog,
)
from novelwiki.modules.acquisition.application import ListScraperAdapters


def build_adapter_catalog_query() -> ListScraperAdapters:
    return ListScraperAdapters(BuiltinScraperAdapterCatalog())


async def build_import_worker_repository():
    from novelwiki.modules.acquisition.adapters.outbound.worker_jobs import (
        PostgresImportWorkerRepository,
    )
    from novelwiki.platform.database import init_db_pool
    return PostgresImportWorkerRepository(await init_db_pool())


async def import_worker_owner_can_spend(user_id: int) -> bool:
    from novelwiki.modules.identity.adapters.outbound.worker_lookup import (
        PostgresIdentityWorkerLookup,
    )
    from novelwiki.platform.database import init_db_pool
    import novelwiki.modules.identity.public as quota
    user = await PostgresIdentityWorkerLookup(await init_db_pool()).load_user(user_id)
    return bool(user and quota.spend_allowed(user))


async def gemini_budget_remaining() -> int:
    from novelwiki.platform.config import settings
    from novelwiki.modules.ai_execution.adapters.outbound.providers import (
        gemini_budget_remaining as remaining,
    )
    return await remaining(settings.GEMINI_DAILY_BUDGET)


async def import_job_novel_titles(novel_ids: set[int]) -> dict[int, str]:
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.platform.database import init_db_pool
    pool = await init_db_pool()
    async with pool.acquire() as connection:
        return await PostgresCatalogRepository(connection).novel_titles(novel_ids)
