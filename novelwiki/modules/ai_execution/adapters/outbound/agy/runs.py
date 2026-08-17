from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool
from novelwiki.platform.observability.logging import log_event

logger = logging.getLogger(__name__)


def _provider_label(backend: str) -> str:
    return "OpenAI Codex" if backend == "openai_codex" else "AGY"


async def create_run(
    *, job: dict, workload: str, model: str, runner_version: str | None,
    plugin_version: str, plugin_sha256: str, parent_run_id: uuid.UUID | None = None,
    backend: str = "agy",
) -> uuid.UUID:
    run_id = uuid.uuid4()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ai_execution_runs
              (id, job_id, parent_run_id, user_id, novel_id, workload, backend, model,
               runner_version, plugin_version, plugin_sha256, status, attempt, created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'preparing',$12,now());
            """,
            run_id, int(job["id"]), parent_run_id, job.get("user_id"), job.get("novel_id"),
            workload, backend, model, runner_version, plugin_version, plugin_sha256,
            int(job.get("attempts") or 1),
        )
    provider_label = _provider_label(backend)
    workload_fields = {"ai_workload": workload}
    if backend == "agy":
        workload_fields["agy_workload"] = workload
    log_event(
        logger, logging.INFO, f"{backend}.run_created",
        f"Created {provider_label} {workload} run {run_id} for job {job['id']}.",
        ai_run_id=run_id, parent_run_id=parent_run_id,
        job_id=int(job["id"]), job_kind=job.get("kind"), **workload_fields,
        user_id=job.get("user_id"), novel_id=job.get("novel_id"),
        execution_backend=backend, model=model, runner_version=runner_version,
        plugin_version=plugin_version, plugin_sha256=plugin_sha256,
        attempt=int(job.get("attempts") or 1), status="preparing",
    )
    return run_id


async def update_run(
    run_id: uuid.UUID, *, event_backend: str = "agy", **fields
) -> None:
    if not fields:
        return
    json_fields = {"metrics"}
    sets, args = [], []
    for key, value in fields.items():
        args.append(json.dumps(value) if key in json_fields else value)
        sets.append(f"{key}=${len(args)}")
    args.append(run_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE ai_execution_runs SET {', '.join(sets)} WHERE id=${len(args)};", *args,
        )
    log_fields = {
        key: value for key, value in fields.items()
        if key in {
            "status", "exit_code", "failure_code", "error_summary", "metrics",
            "process_group_id", "process_started_at", "started_at", "finished_at",
        }
    }
    if log_fields:
        status = log_fields.get("status")
        level = logging.ERROR if status in {"failed", "worker_lost"} else (
            logging.WARNING if status == "canceled" else logging.INFO
        )
        log_event(
            logger, level, f"{event_backend}.run_state_changed",
            f"{_provider_label(event_backend)} run {run_id} state changed"
            f"{f' to {status}' if status else ''}.",
            ai_run_id=run_id, changed_fields=sorted(fields), **log_fields,
        )


def workspace_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(settings.AGY_WORK_DIR).expanduser().resolve()).as_posix()
    except ValueError:
        return ""
