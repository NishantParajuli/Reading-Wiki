"""Generic Work worker persistence wiring."""

from __future__ import annotations


def build_worker_runtime():
    from types import SimpleNamespace

    from novelwiki.bootstrap.workers import build_api_worker_registry
    from novelwiki.modules.work.adapters.outbound import postgres
    from novelwiki.modules.work.adapters.outbound.claims import claim_next

    return SimpleNamespace(
        claim_next=claim_next,
        registry_factory=build_api_worker_registry,
        service=postgres,
        worker_state_factory=build_worker_state_service,
    )


async def build_worker_state_service():
    from novelwiki.modules.work.adapters.outbound.worker_state import (
        PostgresWorkerStateRepository,
    )
    from novelwiki.modules.work.application import WorkerStateService
    from novelwiki.modules.identity.adapters.outbound.worker_lookup import (
        PostgresIdentityWorkerLookup,
    )
    from novelwiki.modules.reading.adapters.outbound.translation import (
        PostgresReadingTranslationQuery,
    )
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()
    return WorkerStateService(
        PostgresWorkerStateRepository(pool),
        PostgresIdentityWorkerLookup(pool),
        PostgresReadingTranslationQuery(pool),
    )
