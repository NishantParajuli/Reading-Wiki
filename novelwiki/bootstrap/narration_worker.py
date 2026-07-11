from __future__ import annotations


async def build_narration_worker_state():
    from novelwiki.modules.narration.adapters.outbound.worker_state import (
        PostgresNarrationWorkerRepository,
    )
    from novelwiki.modules.narration.application import NarrationWorkerState
    from novelwiki.platform.database import init_db_pool

    return NarrationWorkerState(
        PostgresNarrationWorkerRepository(await init_db_pool())
    )
