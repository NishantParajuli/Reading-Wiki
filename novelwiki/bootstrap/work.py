"""Work Management application composition."""


async def wire_work_quota_finalization() -> None:
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
        PostgresQuotaTransactionService,
    )
    from novelwiki.modules.identity.public import IdentityQuotaTransactionApi
    from novelwiki.modules.work.adapters.outbound import postgres
    from novelwiki.modules.work.adapters.outbound.transactions import (
        PostgresWorkQuotaFinalizationTransactionService,
    )
    from novelwiki.modules.work.public import WorkQuotaFinalizationTransactionApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        WorkQuotaFinalizationTransactionApi: PostgresWorkQuotaFinalizationTransactionService,
        IdentityQuotaTransactionApi: PostgresQuotaTransactionService,
    }
    postgres.configure_finalization_uow(
        lambda: AsyncpgUnitOfWork(pool, factories)
    )


async def build_work_service():
    await wire_work_quota_finalization()
    from novelwiki.modules.experience.adapters.outbound.operational_projections import (
        PostgresOperationalProjectionRepository,
    )
    from novelwiki.modules.work.adapters.outbound.postgres import PostgresWorkRepository
    from novelwiki.modules.work.application import WorkService
    from novelwiki.platform.database import init_db_pool

    projections = PostgresOperationalProjectionRepository(await init_db_pool())

    class Metadata:
        async def current(self, job_ids):
            return await projections.job_run_metadata(job_ids)

    return WorkService(PostgresWorkRepository(), Metadata())
