from __future__ import annotations

from types import SimpleNamespace

import pytest

from novelwiki.modules.work.adapters.inbound import worker
from novelwiki.platform.observability.logging import current_log_context


@pytest.mark.asyncio
async def test_generic_worker_logs_real_job_kind_attempt_and_outcome(monkeypatch):
    events = []

    async def handler(_job, _context):
        return {"step": 4, "steps": 4}

    class Registry:
        def resolve(self, kind):
            assert kind == "codex_build"
            return handler

    class Service:
        final_state = {
            "status": "done", "stage": "done",
            "progress": {"step": 4, "steps": 4},
        }

        async def mark_done_if_running(self, _job_id, progress=None):
            self.final_state["progress"] = progress
            return True

        async def finalize(self, _job_id, *, success):
            assert success is True

        async def get_job(self, _job_id):
            return self.final_state

        async def fail_or_retry(self, _job, _error):
            raise AssertionError("successful job must not retry")

    async def audit_record(*_args, **_kwargs):
        return None

    def capture(_logger, _level, event, message, **fields):
        events.append({"event": event, "message": message, **current_log_context(), **fields})

    original_runtime = worker._runtime
    monkeypatch.setattr(worker, "log_event", capture)
    monkeypatch.setattr(worker.audit, "record", audit_record)
    worker.configure_worker_runtime(SimpleNamespace(
        registry_factory=Registry,
        service=Service(),
        worker_state_factory=lambda: None,
    ))
    try:
        await worker._process({
            "id": 42, "kind": "codex_build", "status": "running", "stage": "claimed",
            "user_id": 9, "novel_id": 7, "attempts": 2, "max_attempts": 3,
            "execution_backend": "api", "backend_requested": "auto",
            "backend_model": "model/example", "claim_token": "lease-token",
            "options": {"from_chapter": 10, "to_chapter": 20, "force": True},
        })
    finally:
        worker._runtime = original_runtime

    started = next(item for item in events if item["event"] == "job.started")
    finished = next(item for item in events if item["event"] == "job.attempt_finished")
    done = next(item for item in events if item["event"] == "job.done")

    assert started["job_id"] == 42
    assert started["job_kind"] == "codex_build"
    assert started["attempt"] == 2
    assert started["max_attempts"] == 3
    assert started["from_chapter"] == 10
    assert started["to_chapter"] == 20
    assert "codex_build job 42" in started["message"]
    assert done["job_kind"] == "codex_build"
    assert finished["status"] == "done"
    assert finished["progress"] == {"step": 4, "steps": 4}
    assert finished["duration_ms"] >= 0
