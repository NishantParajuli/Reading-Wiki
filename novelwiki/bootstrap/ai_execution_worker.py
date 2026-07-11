from __future__ import annotations


async def build_agy_worker_state_service():
    from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
        PostgresAgyWorkerStateRepository,
    )
    from novelwiki.modules.ai_execution.application import AgyWorkerStateService
    from novelwiki.modules.identity.adapters.outbound.worker_lookup import (
        PostgresIdentityWorkerLookup,
    )
    from novelwiki.modules.reading.adapters.outbound.translation import (
        PostgresReadingTranslationQuery,
    )
    from novelwiki.modules.work.adapters.outbound.worker_state import (
        PostgresWorkerStateRepository,
    )
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()
    return AgyWorkerStateService(
        PostgresAgyWorkerStateRepository(pool),
        PostgresIdentityWorkerLookup(pool),
        PostgresReadingTranslationQuery(pool),
        PostgresWorkerStateRepository(pool),
    )


async def active_agy_job_count(user_id: int) -> int:
    from novelwiki.modules.work.adapters.outbound.worker_state import PostgresWorkerStateRepository
    from novelwiki.platform.database import init_db_pool
    return await PostgresWorkerStateRepository(await init_db_pool()).active_job_count(user_id)


async def revoked_agy_job_ids(user_id: int, kinds: list[str]) -> list[int]:
    from novelwiki.modules.work.adapters.outbound.worker_state import PostgresWorkerStateRepository
    from novelwiki.platform.database import init_db_pool
    return await PostgresWorkerStateRepository(await init_db_pool()).revoked_job_ids(
        user_id, kinds
    )


async def identity_user_exists(user_id: int) -> bool:
    from novelwiki.modules.identity.adapters.outbound.worker_lookup import PostgresIdentityWorkerLookup
    from novelwiki.platform.database import init_db_pool
    return await PostgresIdentityWorkerLookup(await init_db_pool()).load_user(user_id) is not None


async def ai_policy_for_user(user_id: int) -> dict | None:
    from novelwiki.modules.ai_execution.adapters.outbound.policy import get_policy
    return await get_policy(user_id)


async def resumable_ai_runs(job_id: int, workloads: tuple[str, ...]) -> list[dict]:
    from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
        PostgresAgyWorkerStateRepository,
    )
    from novelwiki.platform.database import init_db_pool
    return await PostgresAgyWorkerStateRepository(
        await init_db_pool()
    ).resumable_runs(job_id, workloads)
