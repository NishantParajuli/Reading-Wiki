from __future__ import annotations


async def build_experience_projection_service():
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.experience.adapters.outbound.projections import (
        PostgresExperienceProjectionRepository,
    )
    from novelwiki.modules.experience.application import ExperienceProjectionService
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()

    class CatalogReadBridge:
        async def require_readable(self, novel_id, principal):
            async with pool.acquire() as connection:
                return await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_readable(novel_id, principal)

    return ExperienceProjectionService(
        PostgresExperienceProjectionRepository(pool), CatalogReadBridge()
    )
