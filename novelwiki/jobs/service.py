"""Stable compatibility wrapper for Work Management persistence operations."""

from novelwiki.modules.work.adapters.outbound import postgres as _implementation


class _LazyFinalizationUow:
    def __init__(self):
        self._delegate = None

    async def __aenter__(self):
        from novelwiki.modules.identity.adapters.outbound.postgres_quota import PostgresQuotaTransactionService
        from novelwiki.modules.identity.public import IdentityQuotaTransactionApi
        from novelwiki.modules.work.adapters.outbound.transactions import PostgresWorkQuotaFinalizationTransactionService
        from novelwiki.modules.work.public import WorkQuotaFinalizationTransactionApi
        from novelwiki.platform.database import AsyncpgUnitOfWork, init_db_pool
        self._delegate = AsyncpgUnitOfWork(await init_db_pool(), {
            WorkQuotaFinalizationTransactionApi: PostgresWorkQuotaFinalizationTransactionService,
            IdentityQuotaTransactionApi: PostgresQuotaTransactionService,
        })
        return await self._delegate.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback):
        return await self._delegate.__aexit__(exc_type, exc, traceback)


_implementation.configure_finalization_uow(_LazyFinalizationUow)


async def create_job(*args, **kwargs):
    if kwargs.get("execution_backend") == "agy" and "policy_lookup" not in kwargs:
        from novelwiki.modules.ai_execution.adapters.outbound.policy import get_policy

        kwargs["policy_lookup"] = get_policy
    return await _implementation.create_job(*args, **kwargs)


def __getattr__(name):
    return getattr(_implementation, name)
