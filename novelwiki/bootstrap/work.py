"""Work Management application composition."""


async def build_work_service():
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
