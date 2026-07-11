"""Generic Work worker persistence wiring."""

from __future__ import annotations


async def build_worker_state_service():
    from novelwiki.modules.work.adapters.outbound.worker_state import (
        PostgresWorkerStateRepository,
    )
    from novelwiki.modules.work.application import WorkerStateService
    from novelwiki.platform.database import init_db_pool

    return WorkerStateService(PostgresWorkerStateRepository(await init_db_pool()))
