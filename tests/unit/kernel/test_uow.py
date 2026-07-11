from __future__ import annotations

import pytest

from novelwiki.platform.database.uow import AsyncpgUnitOfWork


class CapabilityA: ...
class CapabilityB: ...


class _Transaction:
    def __init__(self, events): self.events = events
    async def __aenter__(self): self.events.append("begin")
    async def __aexit__(self, exc_type, exc, traceback): self.events.append("rollback" if exc else "commit")


class _Acquire:
    def __init__(self, connection, events): self.connection, self.events = connection, events
    async def __aenter__(self): self.events.append("acquire"); return self.connection
    async def __aexit__(self, exc_type, exc, traceback): self.events.append("release")


class _Connection:
    def __init__(self, events): self.events = events
    def transaction(self): return _Transaction(self.events)


class _Pool:
    def __init__(self): self.events = []; self.connection = _Connection(self.events)
    def acquire(self): return _Acquire(self.connection, self.events)


@pytest.mark.asyncio
async def test_module_capabilities_share_one_hidden_connection():
    pool = _Pool()
    seen = []
    factories = {
        CapabilityA: lambda connection: seen.append(connection) or CapabilityA(),
        CapabilityB: lambda connection: seen.append(connection) or CapabilityB(),
    }
    async with AsyncpgUnitOfWork(pool, factories) as uow:
        first = uow.transaction.bind(CapabilityA)
        assert uow.transaction.bind(CapabilityA) is first
        uow.transaction.bind(CapabilityB)
    assert seen == [pool.connection, pool.connection]
    assert pool.events == ["acquire", "begin", "commit", "release"]


@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_on_failure():
    pool = _Pool()
    with pytest.raises(RuntimeError):
        async with AsyncpgUnitOfWork(pool):
            raise RuntimeError("boom")
    assert pool.events == ["acquire", "begin", "rollback", "release"]
