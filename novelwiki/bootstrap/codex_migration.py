"""Composition root for the HTTP-facing Codex migration slice."""

from __future__ import annotations


async def build_codex_migration_service():
    from novelwiki.modules.codex.adapters.outbound.agent_bridge import (
        CodexAgentGateway,
    )
    from novelwiki.modules.codex.adapters.outbound.migration_bridges import (
        BackendResolutionBridge, CodexQuotaBridge, CodexWorkBridge,
        AiCostGateway, ReadingCeilingGateway,
    )
    from novelwiki.modules.codex.adapters.outbound.postgres_queries import (
        PostgresCodexQueries, PostgresEntityMerger,
    )
    from novelwiki.modules.codex.application import (
        CodexCommandService, CodexMigrationService, CodexQueryService,
    )
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
        PostgresQuotaRepository,
    )
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import (
        CatalogAccessService, CatalogTransactionService,
    )
    from novelwiki.platform.config import settings
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()

    class CatalogEditBridge:
        async def require_editable(self, novel_id, principal):
            async with pool.acquire() as connection:
                await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_editable(novel_id, principal)

        async def enable_codex(self, novel_id):
            async with pool.acquire() as connection:
                async with connection.transaction():
                    await CatalogTransactionService(
                        PostgresCatalogRepository(connection)
                    ).enable_codex(novel_id)
    queries = CodexQueryService(
        ReadingCeilingGateway(pool), PostgresCodexQueries(pool),
        CodexAgentGateway(), AiCostGateway(),
        ask_max_query_chars=settings.ASK_MAX_QUERY_CHARS,
        ask_requires_verified=settings.ASK_REQUIRE_VERIFIED,
        profile_requires_verified=settings.ENTITY_PROFILE_SYNTH_REQUIRE_VERIFIED,
        profile_model=settings.MODEL_PRO,
    )
    commands = CodexCommandService(
        CatalogEditBridge(), BackendResolutionBridge(),
        CodexWorkBridge(),
        CodexQuotaBridge(QuotaService(PostgresQuotaRepository(pool=pool))),
        PostgresEntityMerger(pool), settings.AGY_MAX_ATTEMPTS,
    )
    return CodexMigrationService(queries, commands)


def codex_principal_from_user(user: dict):
    from novelwiki.modules.identity.adapters.principals import principal_from_user
    return principal_from_user(user)


async def build_codex_principal_factory():
    """Dependency-provider shape expected by the native inbound adapter."""
    return codex_principal_from_user


__all__ = [
    "build_codex_migration_service", "build_codex_principal_factory",
    "codex_principal_from_user",
]
