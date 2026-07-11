from __future__ import annotations


async def build_identity_admin_service():
    from novelwiki.ai_backend.policy import cancel_revoked_jobs
    from novelwiki.modules.identity.adapters.outbound.postgres_admin import (
        PostgresIdentityAdminTransactionService,
    )
    from novelwiki.modules.identity.application import IdentityAdminService
    from novelwiki.modules.identity.public import IdentityAdminTransactionApi
    from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool

    pool = await init_db_pool()
    factories = {
        IdentityAdminTransactionApi: PostgresIdentityAdminTransactionService,
    }

    async def revoke_ai_jobs(user_id: int):
        await cancel_revoked_jobs(user_id, None)

    return IdentityAdminService(
        lambda: AsyncpgUnitOfWork(pool, factories), revoke_ai_jobs
    )
