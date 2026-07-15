from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

import pytest

from novelwiki.modules.work.adapters.outbound.structured_logging import (
    StructuredJobObserver,
)
from novelwiki.modules.work.application import WorkPrincipal, WorkService


def _job(**overrides):
    job = {
        "id": 8,
        "kind": "codex_build",
        "user_id": 1,
        "novel_id": 33,
        "status": "running",
        "stage": "extracting",
        "progress": {"chapter": 5, "chunks": 8},
        "options": {"force": True, "from_chapter": 5, "to_chapter": 10},
        "attempts": 1,
        "max_attempts": 5,
        "execution_backend": "agy",
        "backend_requested": "agy",
        "backend_model": "Gemini 3.5 Flash (High)",
        "backend_fallback_allowed": False,
        "current_run_id": UUID("3da33b7a-1a86-498c-a329-02ebbf82ed74"),
        "current_run_workload": "codex_extract",
        "current_run_status": "running",
        "current_run_attempt": 1,
        "current_run_model": "Gemini 3.5 Flash (High)",
        "current_run_runner_version": "1.1.1",
        "current_plugin_version": "1.0.2",
        "current_run_process_group_id": 1616466,
        "current_run_metrics": {"items": 51},
        "created_at": datetime(2026, 7, 14, 16, 55, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 14, 17, 2, tzinfo=UTC),
    }
    job.update(overrides)
    return job


def test_observer_emits_rich_snapshot_once_and_then_only_on_change(caplog):
    observer = StructuredJobObserver()
    caplog.set_level(logging.INFO)

    observer.observe([_job()])
    observer.observe([_job()])

    records = [record for record in caplog.records if record.event == "job.snapshot_changed"]
    assert len(records) == 1
    fields = records[0].event_fields
    assert fields["job_id"] == 8
    assert fields["job_kind"] == "codex_build"
    assert fields["agy_workload"] == "codex_extract"
    assert fields["ai_run_id"] == UUID("3da33b7a-1a86-498c-a329-02ebbf82ed74")
    assert fields["status"] == "running"
    assert fields["stage"] == "extracting"
    assert fields["progress"] == {"chapter": 5, "chunks": 8}
    assert fields["attempt"] == 1
    assert fields["max_attempts"] == 5
    assert fields["backend_model"] == "Gemini 3.5 Flash (High)"
    assert fields["process_group_id"] == 1616466
    assert fields["metrics"] == {"items": 51}
    assert fields["novel_id"] == 33
    assert fields["user_id"] == 1
    assert fields["changed_fields"] == ["initial_snapshot"]

    observer.observe([
        _job(
            status="failed",
            current_run_status="failed",
            current_run_failure_code="agy_artifact_invalid",
            current_run_error_summary="AgyValidationError",
        )
    ])
    changed = [record for record in caplog.records if record.event == "job.snapshot_changed"][-1]
    assert changed.levelno == logging.ERROR
    assert changed.event_fields["failure_code"] == "agy_artifact_invalid"
    assert changed.event_fields["error_summary"] == "AgyValidationError"
    assert changed.event_fields["changed_fields"] == [
        "error_summary",
        "failure_code",
        "run_status",
        "status",
    ]


@pytest.mark.asyncio
async def test_work_service_observes_jobs_after_run_metadata_enrichment():
    job = _job(current_run_id=None, current_run_workload=None)

    class Repository:
        async def list_jobs(self, **_filters):
            return [dict(job)]

        def job_view(self, row):
            return {"id": row["id"], "current_run_id": row.get("current_run_id")}

    class Metadata:
        async def current(self, job_ids):
            assert job_ids == {8}
            return {8: {"current_run_id": "run-8", "current_run_workload": "codex_extract"}}

    class Observer:
        observed = None

        def observe(self, jobs):
            self.observed = jobs

    observer = Observer()
    service = WorkService(Repository(), Metadata(), observer)

    result = await service.list_jobs(WorkPrincipal(user_id=1))

    assert result == [{"id": 8, "current_run_id": "run-8"}]
    assert observer.observed[0]["current_run_workload"] == "codex_extract"
