"""Direct-call compatibility exports for Experience product routes."""

from novelwiki.modules.experience.adapters.inbound.http import *  # noqa: F403
from novelwiki.modules.experience.adapters.inbound import http as _native
from novelwiki.modules.codex.application.services import RECAP_QUESTION
from novelwiki.modules.codex.public import answer_question, get_bm25_manager


async def api_recap(novel_id: int, req: RecapRequest, user: dict):  # noqa: F405
    """Compose explicit Codex dependencies for legacy direct-call fixtures."""
    from novelwiki.bootstrap.codex_migration import (
        build_codex_migration_service,
        codex_principal_from_user,
    )
    from novelwiki.modules.codex.adapters.outbound.agent_bridge import CodexAgentGateway

    class DirectCallAgent(CodexAgentGateway):
        async def ensure_index(self, target_novel_id):
            await get_bm25_manager(target_novel_id).ensure_loaded()

        async def answer(self, target_novel_id, question, ceiling):
            return await answer_question(target_novel_id, question, ceiling.value)

    service = await build_codex_migration_service(DirectCallAgent())
    return await _native.api_recap(
        novel_id,
        req,
        user=user,
        service=service,
        principal_factory=codex_principal_from_user,
    )
