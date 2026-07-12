from __future__ import annotations


def build_agy_worker_runtime():
    from novelwiki.bootstrap.ai_execution import wire_ai_policy
    wire_ai_policy()
    from types import SimpleNamespace

    from novelwiki.bootstrap.workers import build_agy_worker_registry
    from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import (
        AgyCanceled,
        AgyError,
        PROVIDER_WAIT_CODES,
        safe_error_summary,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.agy.preflight import run_preflight
    from novelwiki.modules.ai_execution.adapters.outbound.agy.runner import (
        process_identity_matches,
        terminate_process_group,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import (
        cleanup_expired_workspaces,
        validate_work_root,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.policy import (
        get_policy,
        model_for,
        reauthorize_job,
    )
    from novelwiki.modules.work.adapters.inbound.worker import (
        _heartbeat,
        _recover_stale_leases,
        _release_due_provider_waits,
    )
    from novelwiki.modules.work.adapters.outbound import postgres
    from novelwiki.modules.work.adapters.outbound.claims import claim_next

    return SimpleNamespace(
        agy_error=AgyError,
        canceled_error=AgyCanceled,
        claim_next=claim_next,
        cleanup_expired_workspaces=cleanup_expired_workspaces,
        get_policy=get_policy,
        heartbeat=_heartbeat,
        is_canceled_error=lambda exc: isinstance(exc, AgyCanceled),
        is_provider_wait_code=lambda code: code in PROVIDER_WAIT_CODES,
        model_for=model_for,
        process_identity_matches=process_identity_matches,
        reauthorize_job=reauthorize_job,
        recover_stale_leases=_recover_stale_leases,
        registry_factory=build_agy_worker_registry,
        release_due_provider_waits=_release_due_provider_waits,
        run_preflight=run_preflight,
        safe_error_summary=safe_error_summary,
        terminate_process_group=terminate_process_group,
        validate_work_root=validate_work_root,
        worker_state_factory=build_agy_worker_state_service,
        work_service=postgres,
    )


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


async def build_agy_catalog_access():
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()

    class CatalogAccess:
        async def require_editable(self, novel_id, principal):
            async with pool.acquire() as connection:
                return await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_editable(novel_id, principal)

    return CatalogAccess()


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
