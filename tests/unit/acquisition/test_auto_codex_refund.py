from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_reserve_auto_codex_is_refunded_when_schedule_deduplicates(monkeypatch):
    from novelwiki.bootstrap.acquisition_runtime import build_acquisition_runtime
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.work.adapters.outbound import postgres as work

    refunds = []

    async def create_job(*args, **kwargs):
        return 77, False

    async def refund(self, user_id, kind, units):
        refunds.append((user_id, kind, units))
        return units

    async def pool():
        return object()

    monkeypatch.setattr(work, "create_job", create_job)
    monkeypatch.setattr(QuotaService, "refund", refund)
    monkeypatch.setattr("novelwiki.platform.database.init_db_pool", pool)

    await build_acquisition_runtime().schedule_codex(5, 1.0, 9.0, 42)
    assert refunds == [(42, "codex_builds", 1)]


@pytest.mark.asyncio
async def test_reserve_auto_codex_is_refunded_when_schedule_fails(monkeypatch):
    from novelwiki.bootstrap.acquisition_runtime import build_acquisition_runtime
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.work.adapters.outbound import postgres as work

    refunds = []

    async def create_job(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    async def refund(self, user_id, kind, units):
        refunds.append((user_id, kind, units))
        return units

    async def pool():
        return object()

    monkeypatch.setattr(work, "create_job", create_job)
    monkeypatch.setattr(QuotaService, "refund", refund)
    monkeypatch.setattr("novelwiki.platform.database.init_db_pool", pool)

    with pytest.raises(RuntimeError, match="queue unavailable"):
        await build_acquisition_runtime().schedule_codex(5, 1.0, 9.0, 42)
    assert refunds == [(42, "codex_builds", 1)]
