from __future__ import annotations

import pytest

from novelwiki.modules.identity.public import IdentityQuotaTransactionApi
from novelwiki.modules.work.public import (
    JobQuotaSettlement,
    WorkQuotaFinalizationTransactionApi,
)
from novelwiki.workflows.finalize_job_quota import finalize_job_quota


class Bindings:
    def __init__(self, work, quota):
        self._values = {
            WorkQuotaFinalizationTransactionApi: work,
            IdentityQuotaTransactionApi: quota,
        }

    def bind(self, capability):
        return self._values[capability]


class FakeUow:
    def __init__(self, work, quota):
        self.transaction = Bindings(work, quota)
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_args):
        self.committed = exc_type is None
        self.rolled_back = exc_type is not None


class Work:
    def __init__(self, settlement):
        self.settlement = settlement

    async def finalize_quota(self, job_id, success):
        assert (job_id, success) == (7, False)
        return self.settlement


class Quota:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def refund(self, user_id, kind, units=1):
        self.calls.append((user_id, kind, units))
        if self.error:
            raise self.error
        return units


@pytest.mark.asyncio
async def test_finalization_binds_both_owners_to_one_uow():
    settlement = JobQuotaSettlement(3, 9, "codex_builds", 1)
    quota = Quota()
    uow = FakeUow(Work(settlement), quota)

    result = await finalize_job_quota(lambda: uow, 7, False)

    assert result == (settlement, 1)
    assert quota.calls == [(3, "codex_builds", 1)]
    assert uow.committed and not uow.rolled_back


@pytest.mark.asyncio
async def test_refund_failure_rolls_back_the_shared_uow():
    settlement = JobQuotaSettlement(3, 9, "codex_builds", 1)
    uow = FakeUow(Work(settlement), Quota(RuntimeError("injected")))

    with pytest.raises(RuntimeError, match="injected"):
        await finalize_job_quota(lambda: uow, 7, False)

    assert uow.rolled_back and not uow.committed


@pytest.mark.asyncio
async def test_already_finalized_is_idempotent_and_skips_identity():
    quota = Quota()
    uow = FakeUow(Work(None), quota)

    assert await finalize_job_quota(lambda: uow, 7, False) == (None, 0)
    assert quota.calls == []
