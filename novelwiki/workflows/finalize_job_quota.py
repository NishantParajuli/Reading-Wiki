from __future__ import annotations

from collections.abc import Callable

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.identity.public import IdentityQuotaTransactionApi
from novelwiki.modules.work.public import (
    JobQuotaSettlement,
    WorkQuotaFinalizationTransactionApi,
)


async def finalize_job_quota(
    uow_factory: Callable[[], UnitOfWork], job_id: int, success: bool
) -> tuple[JobQuotaSettlement | None, int]:
    """Atomically finalize a Work reservation and refund it through Identity."""
    async with uow_factory() as uow:
        work = uow.transaction.bind(WorkQuotaFinalizationTransactionApi)
        settlement = await work.finalize_quota(job_id, success)
        if settlement is None:
            return None, 0
        refunded = 0
        if (
            settlement.quota_kind
            and settlement.user_id is not None
            and settlement.refundable_units > 0
        ):
            quota = uow.transaction.bind(IdentityQuotaTransactionApi)
            refunded = await quota.refund(
                settlement.user_id,
                settlement.quota_kind,
                settlement.refundable_units,
            )
    return settlement, refunded
