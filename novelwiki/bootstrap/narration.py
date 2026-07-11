from __future__ import annotations


async def build_narration_service():
    from novelwiki.config.settings import settings
    from novelwiki.db.connection import get_db_pool
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
        PostgresQuotaRepository,
    )
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.catalog.adapters.outbound.postgres import (
        PostgresCatalogRepository,
    )
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.narration.adapters.outbound.migration import (
        IdentityNarrationQuota, LegacyChapterTextAdapter,
        LegacyNarrationJobs, LocalAudioFiles, NarrationSidecar,
        PostgresNarrationQueries,
    )
    from novelwiki.modules.narration.application import NarrationService

    pool = await get_db_pool()
    return NarrationService(
        _PoolCatalogAccess(pool, CatalogAccessService, PostgresCatalogRepository),
        LegacyChapterTextAdapter(),
        IdentityNarrationQuota(QuotaService(PostgresQuotaRepository(pool=pool))),
        PostgresNarrationQueries(pool),
        LegacyNarrationJobs(),
        NarrationSidecar(),
        LocalAudioFiles(),
        default_voice=settings.TTS_DEFAULT_VOICE,
        enabled=settings.TTS_ENABLED,
        max_batch_chapters=settings.TTS_MAX_BATCH_CHAPTERS,
    )


def build_narration_principal_factory():
    from novelwiki.modules.identity.adapters.principals import principal_from_user
    return principal_from_user


class _PoolCatalogAccess:
    def __init__(self, pool, service_type, repository_type):
        self._pool = pool
        self._service_type = service_type
        self._repository_type = repository_type

    async def require_readable(self, novel_id, principal):
        async with self._pool.acquire() as connection:
            await self._service_type(
                self._repository_type(connection)
            ).require_readable(novel_id, principal)
