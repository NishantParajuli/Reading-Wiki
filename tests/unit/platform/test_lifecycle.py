from __future__ import annotations

import pytest

from novelwiki.bootstrap.lifecycle import ApplicationLifecycle, LifecycleHook


@pytest.mark.asyncio
async def test_lifecycle_preserves_startup_and_explicit_shutdown_order():
    events: list[str] = []

    def record(value: str):
        async def callback():
            events.append(value)
        return callback

    lifecycle = ApplicationLifecycle([
        LifecycleHook("schema", record("start:schema")),
        LifecycleHook(
            "pool", record("start:pool"), record("stop:pool"),
            fatal_start=True, shutdown_order=30,
        ),
        LifecycleHook(
            "import", record("start:import"), record("stop:import"),
            shutdown_order=10,
        ),
        LifecycleHook(
            "jobs", record("start:jobs"), record("stop:jobs"),
            shutdown_order=20,
        ),
    ])

    assert lifecycle.startup_order == ("schema", "pool", "import", "jobs")
    assert lifecycle.shutdown_order == ("import", "jobs", "pool")
    await lifecycle.start()
    await lifecycle.stop()
    assert events == [
        "start:schema", "start:pool", "start:import", "start:jobs",
        "stop:import", "stop:jobs", "stop:pool",
    ]


@pytest.mark.asyncio
async def test_nonfatal_start_failure_continues_but_fatal_failure_stops():
    events: list[str] = []

    async def fail():
        raise RuntimeError("boom")

    async def later():
        events.append("later")

    lifecycle = ApplicationLifecycle([
        LifecycleHook("cleanup", fail),
        LifecycleHook("worker", later),
    ])
    await lifecycle.start()
    assert events == ["later"]

    fatal = ApplicationLifecycle([
        LifecycleHook("pool", fail, fatal_start=True),
        LifecycleHook("worker", later),
    ])
    with pytest.raises(RuntimeError, match="boom"):
        await fatal.start()
    assert events == ["later"]


def test_lifecycle_rejects_duplicate_hook_names():
    with pytest.raises(ValueError, match="unique"):
        ApplicationLifecycle([LifecycleHook("worker"), LifecycleHook("worker")])
