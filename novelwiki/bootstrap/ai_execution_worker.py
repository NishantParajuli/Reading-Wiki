from __future__ import annotations


async def build_agy_worker_state_service():
    from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
        PostgresAgyWorkerStateRepository,
    )
    from novelwiki.modules.ai_execution.application import AgyWorkerStateService
    from novelwiki.platform.database import init_db_pool

    return AgyWorkerStateService(
        PostgresAgyWorkerStateRepository(await init_db_pool())
    )
