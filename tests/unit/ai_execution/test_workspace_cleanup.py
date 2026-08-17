from __future__ import annotations

import pytest

from novelwiki.modules.ai_execution.adapters.outbound.agy import workspace


@pytest.mark.asyncio
async def test_agy_cleanup_selects_only_agy_run_records(tmp_path, monkeypatch):
    queries: list[str] = []

    class Connection:
        async def fetch(self, query, *_args):
            queries.append(query)
            return []

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def get_pool():
        return Pool()

    monkeypatch.setattr(workspace, "validate_work_root", lambda: tmp_path)
    monkeypatch.setattr("novelwiki.platform.database.get_db_pool", get_pool)

    assert await workspace.cleanup_expired_workspaces() == 0
    assert "backend='agy'" in queries[0]
