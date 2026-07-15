"""Web-process job snapshots for replacing noisy job-list access records."""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import Any

from novelwiki.platform.observability.logging import log_event

logger = logging.getLogger(__name__)

_WORKLOADS = {
    "codex_build": "codex_extract",
    "translate": "translate_batch",
    "agy_smoke": "smoke_test",
}
_MAX_SNAPSHOTS = 2048


def _snapshot(job: dict) -> dict[str, Any]:
    options = job.get("options") or {}
    execution_backend = job.get("execution_backend") or "api"
    return {
        "job_system": "generic",
        "job_id": int(job["id"]),
        "job_kind": job.get("kind"),
        "agy_workload": job.get("current_run_workload") or (
            _WORKLOADS.get(job.get("kind")) if execution_backend == "agy" else None
        ),
        "user_id": job.get("user_id"),
        "novel_id": job.get("novel_id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "progress": job.get("progress") or {},
        "attempt": int(job.get("attempts") or 0),
        "max_attempts": int(job.get("max_attempts") or 0),
        "execution_backend": execution_backend,
        "backend_requested": job.get("backend_requested") or "auto",
        "backend_model": job.get("backend_model"),
        "backend_policy_version": job.get("backend_policy_version"),
        "fallback_allowed": bool(job.get("backend_fallback_allowed")),
        "fallback_from": job.get("backend_fallback_from"),
        "ai_run_id": job.get("current_run_id"),
        "parent_run_id": job.get("current_run_parent_id"),
        "run_status": job.get("current_run_status"),
        "run_attempt": job.get("current_run_attempt"),
        "model": job.get("current_run_model"),
        "runner_version": job.get("current_run_runner_version"),
        "plugin_version": job.get("current_plugin_version"),
        "plugin_sha256": job.get("current_run_plugin_sha256"),
        "input_sha256": job.get("current_run_input_sha256"),
        "output_sha256": job.get("current_run_output_sha256"),
        "workspace_relpath": job.get("current_run_workspace_relpath"),
        "process_group_id": job.get("current_run_process_group_id"),
        "process_started_at": job.get("current_run_process_started_at"),
        "exit_code": job.get("current_run_exit_code"),
        "failure_code": job.get("current_run_failure_code"),
        "error_summary": job.get("current_run_error_summary"),
        "metrics": job.get("current_run_metrics") or {},
        "run_started_at": job.get("current_run_started_at"),
        "run_finished_at": job.get("current_run_finished_at"),
        "run_created_at": job.get("current_run_created_at"),
        "job_error": job.get("error"),
        "cancel_requested": job.get("cancel_requested_at") is not None,
        "not_before": job.get("not_before"),
        "quota_kind": job.get("quota_kind"),
        "quota_reserved": job.get("quota_reserved"),
        "quota_consumed": job.get("quota_consumed"),
        "quota_finalized": job.get("quota_finalized"),
        "option_keys": sorted(options),
        "force": bool(options.get("force")),
        "source_id": options.get("source_id"),
        "max_chapters": options.get("max_chapters"),
        "from_chapter": options.get("from_chapter"),
        "to_chapter": options.get("to_chapter"),
        "seed_from_codex": options.get("seed_from_codex"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def _fingerprint(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, sort_keys=True, default=str, separators=(",", ":"))


class StructuredJobObserver:
    """Emit one rich web log record when a listed job's durable snapshot changes."""

    def __init__(self, *, max_snapshots: int = _MAX_SNAPSHOTS) -> None:
        self._max_snapshots = max(1, max_snapshots)
        self._snapshots: OrderedDict[int, tuple[str, dict[str, Any]]] = OrderedDict()

    def observe(self, jobs: list[dict]) -> None:
        for job in jobs:
            snapshot = _snapshot(job)
            job_id = int(snapshot["job_id"])
            fingerprint = _fingerprint(snapshot)
            previous = self._snapshots.get(job_id)
            if previous is not None and previous[0] == fingerprint:
                self._snapshots.move_to_end(job_id)
                continue

            changed_fields = (
                ["initial_snapshot"]
                if previous is None
                else sorted(
                    key for key, value in snapshot.items()
                    if previous[1].get(key) != value
                )
            )
            self._snapshots[job_id] = (fingerprint, snapshot)
            self._snapshots.move_to_end(job_id)
            while len(self._snapshots) > self._max_snapshots:
                self._snapshots.popitem(last=False)

            status = str(snapshot.get("status") or "unknown")
            run_status = snapshot.get("run_status")
            level = logging.ERROR if status == "failed" or run_status == "failed" else (
                logging.WARNING
                if status in {"waiting_provider", "canceled"}
                or run_status in {"canceled", "worker_lost"}
                else logging.INFO
            )
            backend = snapshot.get("execution_backend")
            workload = snapshot.get("agy_workload") or snapshot.get("job_kind")
            run = f"; run {snapshot['ai_run_id']} is {run_status}" if snapshot.get("ai_run_id") else ""
            model = f" using {snapshot['backend_model']}" if snapshot.get("backend_model") else ""
            log_event(
                logger,
                level,
                "job.snapshot_changed",
                f"{snapshot.get('job_kind')} job {job_id} is {status} at "
                f"{snapshot.get('stage') or workload} (attempt {snapshot.get('attempt')}/"
                f"{snapshot.get('max_attempts')}) via {backend}{model}{run}.",
                changed_fields=changed_fields,
                **snapshot,
            )


web_job_observer = StructuredJobObserver()


__all__ = ["StructuredJobObserver", "web_job_observer"]
