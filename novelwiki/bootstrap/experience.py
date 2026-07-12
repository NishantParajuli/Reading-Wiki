from __future__ import annotations


async def build_experience_projection_service():
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.experience.adapters.outbound.projections import (
        PostgresExperienceProjectionRepository,
    )
    from novelwiki.modules.experience.application import ExperienceProjectionService
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()

    class CatalogReadBridge:
        async def require_readable(self, novel_id, principal):
            async with pool.acquire() as connection:
                return await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_readable(novel_id, principal)

    return ExperienceProjectionService(
        PostgresExperienceProjectionRepository(pool), CatalogReadBridge()
    )


async def build_operational_projection_repository():
    from novelwiki.modules.experience.adapters.outbound.operational_projections import (
        PostgresOperationalProjectionRepository,
    )
    from novelwiki.platform.database import init_db_pool
    return PostgresOperationalProjectionRepository(await init_db_pool())


async def job_run_metadata(job_ids: set[int]) -> dict[int, dict]:
    return await (await build_operational_projection_repository()).job_run_metadata(job_ids)


async def build_experience_admin_commands():
    from novelwiki.bootstrap.ai_execution import wire_ai_policy
    wire_ai_policy()
    from novelwiki.modules.experience.application.admin_commands import ExperienceAdminCommands
    from novelwiki.modules.ai_execution.adapters.outbound import policy
    from novelwiki.modules.work.adapters.outbound import postgres as service
    from novelwiki.platform.config import settings
    from novelwiki.platform.observability import audit

    class AiBridge:
        get_policy = staticmethod(policy.get_policy)
        upsert_policy = staticmethod(policy.upsert_policy)
        delete_policy = staticmethod(policy.delete_policy)
        worker_available = staticmethod(policy.worker_available)

    class WorkBridge:
        retry_waiting = staticmethod(service.retry_waiting)

        @staticmethod
        async def create_smoke(admin_id):
            return await service.create_job(
                "agy_smoke", novel_id=None, user_id=admin_id, options={},
                idempotency_key="agy-admin-smoke", max_attempts=1,
                backend_requested="agy", execution_backend="agy",
                backend_model=settings.AGY_MODEL_TRANSLATE,
            )

    class AuditBridge:
        @staticmethod
        async def record(event, user_id, data):
            await audit.record(event, user_id=user_id, data=data)

    return ExperienceAdminCommands(AiBridge(), WorkBridge(), AuditBridge())
