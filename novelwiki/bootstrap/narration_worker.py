from __future__ import annotations


def build_narration_worker_runtime():
    from types import SimpleNamespace

    from novelwiki.bootstrap.reading_migration import build_reading_narration_gateway
    from novelwiki.modules.identity.adapters.outbound import quota_compat
    from novelwiki.modules.narration.adapters.outbound import sidecar

    async def resolve_chapter_text(novel_id, number, user):
        gateway = await build_reading_narration_gateway()
        return await gateway.resolve_narration_text(
            novel_id, number, int(user["id"]) if isinstance(user, dict) else None
        )

    return SimpleNamespace(
        quota=quota_compat,
        resolve_chapter_text=resolve_chapter_text,
        tts_client=sidecar,
        worker_state_factory=build_narration_worker_state,
    )


async def build_narration_worker_state():
    from novelwiki.modules.narration.adapters.outbound.worker_state import (
        PostgresNarrationWorkerRepository,
    )
    from novelwiki.modules.narration.application import NarrationWorkerState
    from novelwiki.modules.identity.adapters.outbound.worker_lookup import (
        PostgresIdentityWorkerLookup,
    )
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()
    return NarrationWorkerState(
        PostgresNarrationWorkerRepository(pool), PostgresIdentityWorkerLookup(pool)
    )
