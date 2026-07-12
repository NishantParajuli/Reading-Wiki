"""Composition wiring for AI Execution policy dependencies."""

from __future__ import annotations


def wire_ai_policy() -> None:
    from novelwiki.modules.ai_execution.adapters.outbound.policy import (
        configure_policy_dependencies,
    )

    class Dependencies:
        @staticmethod
        async def _work_repository():
            from novelwiki.modules.work.adapters.outbound.worker_state import (
                PostgresWorkerStateRepository,
            )
            from novelwiki.platform.database import init_db_pool

            return PostgresWorkerStateRepository(await init_db_pool())

        async def active_job_count(self, user_id: int) -> int:
            return await (await self._work_repository()).active_job_count(user_id)

        async def user_exists(self, user_id: int) -> bool:
            from novelwiki.modules.identity.adapters.outbound.worker_lookup import (
                PostgresIdentityWorkerLookup,
            )
            from novelwiki.platform.database import init_db_pool

            user = await PostgresIdentityWorkerLookup(
                await init_db_pool()
            ).load_user(user_id)
            return user is not None

        async def revoked_job_ids(self, user_id: int, kinds: list[str]) -> list[int]:
            return await (await self._work_repository()).revoked_job_ids(user_id, kinds)

        async def cancel_job(self, job_id: int) -> bool:
            from novelwiki.modules.work.adapters.outbound import postgres

            return await postgres.cancel_job(job_id)

    configure_policy_dependencies(Dependencies())
