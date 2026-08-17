from __future__ import annotations

import pytest

from novelwiki.modules.ai_execution.application.worker import AgyWorkerService
from novelwiki.modules.ai_execution.adapters.outbound.agy import runs
from novelwiki.modules.work.adapters.outbound import postgres


@pytest.mark.asyncio
async def test_openai_worker_exception_uses_its_provider_label():
    messages: list[str] = []

    class Operations:
        @staticmethod
        async def reauthorize(_job):
            return True, "ok", {}

        @staticmethod
        def resolve_handler(_kind):
            raise RuntimeError("boom")

        @staticmethod
        def exception(message):
            messages.append(message)

        @staticmethod
        def is_canceled_error(_error):
            return False

        @staticmethod
        def error_code(_error):
            return "openai_codex_protocol_error"

        @staticmethod
        def error_summary(_error):
            return "safe failure"

        @staticmethod
        async def is_canceled(_job_id):
            return False

        @staticmethod
        def provider_wait_code(_code):
            return False

        @staticmethod
        async def wait_for_provider(_job_id, _code, _summary):
            return None

        @staticmethod
        async def record(_event, _job, **_data):
            return None

    await AgyWorkerService(Operations(), "openai_codex").process(
        {"id": 7, "kind": "codex_build"}, object(), {}
    )

    assert messages == ["OpenAI Codex codex_build job 7 raised RuntimeError."]


@pytest.mark.asyncio
async def test_provider_wait_uses_the_claimed_backend(monkeypatch):
    queries: list[str] = []
    audit_events: list[str] = []
    log_events: list[tuple[str, dict]] = []

    class Connection:
        async def fetchrow(self, query, *_args):
            queries.append(query)
            return {"id": 7, "execution_backend": "openai_codex"}

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

    async def record(event, **_kwargs):
        audit_events.append(event)

    def log_event(_logger, _level, event, _message, **fields):
        log_events.append((event, fields))

    monkeypatch.setattr(postgres, "get_db_pool", get_pool)
    monkeypatch.setattr(postgres.audit, "record", record)
    monkeypatch.setattr(postgres, "log_event", log_event)

    assert await postgres.wait_for_provider(7, "capacity", "safe", 30) is True
    assert "WHEN 'openai_codex' THEN 'waiting for OpenAI Codex provider'" in queries[0]
    assert audit_events == ["openai_codex.run.waiting_provider"]
    assert log_events[0][0] == "openai_codex.run.waiting_provider"
    assert log_events[0][1]["execution_backend"] == "openai_codex"


@pytest.mark.asyncio
async def test_running_cancel_request_uses_the_claimed_backend(monkeypatch):
    audit_events: list[str] = []

    class Connection:
        async def fetchrow(self, _query, *_args):
            return {
                "id": 7,
                "status": "running",
                "execution_backend": "openai_codex",
            }

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

    async def record(event, **_kwargs):
        audit_events.append(event)

    monkeypatch.setattr(postgres, "get_db_pool", get_pool)
    monkeypatch.setattr(postgres.audit, "record", record)
    monkeypatch.setattr(postgres, "log_event", lambda *_args, **_kwargs: None)

    assert await postgres.cancel_job(7) is True
    assert audit_events == ["openai_codex.run.cancel_requested"]


@pytest.mark.asyncio
async def test_run_lifecycle_logs_use_the_selected_provider(monkeypatch):
    events: list[tuple[str, dict]] = []

    class Connection:
        async def execute(self, *_args):
            return "INSERT 0 1"

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

    def log_event(_logger, _level, event, _message, **fields):
        events.append((event, fields))

    monkeypatch.setattr(runs, "get_db_pool", get_pool)
    monkeypatch.setattr(runs, "log_event", log_event)

    run_id = await runs.create_run(
        job={"id": 7, "kind": "openai_codex_smoke", "attempts": 1},
        workload="smoke_test",
        model="gpt-test",
        runner_version="1.0.0",
        plugin_version="contract-test",
        plugin_sha256="abc",
        backend="openai_codex",
    )
    await runs.update_run(
        run_id, event_backend="openai_codex", status="running"
    )

    assert [event for event, _fields in events] == [
        "openai_codex.run_created",
        "openai_codex.run_state_changed",
    ]
    assert events[0][1]["ai_workload"] == "smoke_test"
    assert "agy_workload" not in events[0][1]
