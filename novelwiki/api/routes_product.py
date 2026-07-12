"""Direct-call compatibility exports for Experience product routes."""

from novelwiki.modules.experience.adapters.inbound.http import *  # noqa: F403
from novelwiki.modules.experience.adapters.inbound import http as _native
from novelwiki.modules.codex.application.services import RECAP_QUESTION
from novelwiki.modules.codex.adapters.outbound.agent import answer_question
from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import get_bm25_manager


async def _projections():
    from novelwiki.bootstrap.experience import build_operational_projection_repository
    return await build_operational_projection_repository()


def _quota_projection():
    from types import SimpleNamespace
    from novelwiki.modules.identity.adapters.inbound.presentation import quota_limits
    from novelwiki.modules.identity.adapters.outbound import quota_compat

    return SimpleNamespace(
        is_exempt=quota_compat.is_exempt,
        quota_limits=quota_limits,
        remaining=quota_compat.remaining,
        spend_allowed=quota_compat.spend_allowed,
    )


async def api_activity(status="active", limit=100, user=None):
    return await _native.api_activity(
        status=status, limit=limit, user=user, projections=await _projections()
    )


async def api_home(user=None):
    return await _native.api_home(user=user, projections=await _projections())


async def api_novel_health(novel_id: int, voice_id=None, user=None):
    """Compose Narration coverage for legacy direct-call fixtures."""
    from novelwiki.bootstrap.narration import build_narration_queries

    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()
    async with pool.acquire() as connection:
        return await _native.api_novel_health(
            novel_id,
            voice_id=voice_id,
            user=user,
            narration=await build_narration_queries(),
            catalog=CatalogAccessService(PostgresCatalogRepository(connection)),
            projections=await _projections(),
        )


async def api_cost_estimate(
    novel_id: int, action: str, from_chapter=None, to_chapter=None,
    force: bool = False, voice_id=None, user=None,
):
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()
    async with pool.acquire() as connection:
        return await _native.api_cost_estimate(
            novel_id, action, from_chapter=from_chapter, to_chapter=to_chapter,
            force=force, voice_id=voice_id, user=user,
            catalog=CatalogAccessService(PostgresCatalogRepository(connection)),
            projections=await _projections(),
            quota=_quota_projection(),
        )


async def api_recap(novel_id: int, req: RecapRequest, user: dict):  # noqa: F405
    """Compose explicit Codex dependencies for legacy direct-call fixtures."""
    from novelwiki.bootstrap.codex_migration import (
        build_codex_migration_service,
        codex_principal_from_user,
    )
    from novelwiki.modules.codex.adapters.outbound.agent_bridge import CodexAgentGateway
    from novelwiki.bootstrap.codex_worker import build_codex_runtime

    class DirectCallAgent(CodexAgentGateway):
        async def ensure_index(self, target_novel_id):
            await get_bm25_manager(target_novel_id).ensure_loaded()

        async def answer(self, target_novel_id, question, ceiling):
            return await answer_question(target_novel_id, question, ceiling.value)

    service = await build_codex_migration_service(
        DirectCallAgent(build_codex_runtime())
    )
    return await _native.api_recap(
        novel_id,
        req,
        user=user,
        service=service,
        principal_factory=codex_principal_from_user,
    )
