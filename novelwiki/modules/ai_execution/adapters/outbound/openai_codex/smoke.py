from __future__ import annotations

from datetime import UTC, datetime
from functools import partial

from novelwiki.modules.ai_execution.application.contracts import InputManifest
from novelwiki.modules.ai_execution.application.errors import AgyCanceled
from novelwiki.modules.ai_execution.adapters.outbound.agy.runs import (
    create_run,
    update_run as _update_run,
)
from novelwiki.modules.ai_execution.adapters.outbound.agy.validators import (
    load_json,
    validate_output_manifest,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.runner import (
    build_task_prompt,
    run_openai_codex,
    safe_error_summary,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.workspace import (
    create_run_workspace,
    seal_inputs,
    sha256_file,
    workspace_relpath,
    write_json,
)
from novelwiki.platform.config import settings


update_run = partial(_update_run, event_backend="openai_codex")


async def run_smoke_test(job: dict, preflight, work) -> dict:
    run_id = await create_run(
        job=job,
        workload="smoke_test",
        model=settings.OPENAI_CODEX_MODEL_CODEX,
        runner_version=preflight.version,
        plugin_version=settings.OPENAI_CODEX_CONTRACT_VERSION,
        plugin_sha256=preflight.plugin_sha256 or "",
        backend="openai_codex",
    )
    root = create_run_workspace(int(job["id"]), str(run_id))
    manifest = InputManifest(
        run_id=str(run_id),
        job_id=int(job["id"]),
        workload="smoke_test",
        plugin_version=settings.OPENAI_CODEX_CONTRACT_VERSION,
        model=settings.OPENAI_CODEX_MODEL_CODEX,
        novel_ref="smoke",
        inputs=[],
        created_at=datetime.now(UTC),
    )
    write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json"))
    seal_inputs(root)
    await update_run(
        run_id,
        status="running",
        input_sha256=sha256_file(root / "input" / "manifest.json"),
        workspace_relpath=workspace_relpath(root),
        started_at=datetime.now(UTC),
    )
    result = None
    try:
        result = await run_openai_codex(
            root,
            prompt=build_task_prompt("smoke_test"),
            model=settings.OPENAI_CODEX_MODEL_CODEX,
            cancel_check=lambda: work.is_canceled(int(job["id"])),
        )
        manifest, roles = validate_output_manifest(
            root,
            run_id=str(run_id),
            workload="smoke_test",
            expected_roles={"smoke": 1},
        )
        ready = load_json(roles["smoke"][0])
        if ready != {"ready": "READY"}:
            raise RuntimeError("OpenAI Codex smoke result was invalid")
        await update_run(
            run_id,
            status="completed",
            output_sha256=sha256_file(root / "output" / "manifest.json"),
            exit_code=result.exit_code,
            metrics=result.metrics(),
            finished_at=datetime.now(UTC),
        )
    except Exception as exc:
        metrics = result.metrics() if result is not None else getattr(exc, "metrics", {})
        failure = {
            "status": "canceled" if isinstance(exc, AgyCanceled) else "failed",
            "failure_code": getattr(exc, "code", "unknown"),
            "error_summary": safe_error_summary(exc),
            "metrics": metrics,
            "finished_at": datetime.now(UTC),
        }
        if result is not None:
            failure["exit_code"] = result.exit_code
        await update_run(run_id, **failure)
        raise
    return {
        "ready": True,
        "version": preflight.version,
        "model": settings.OPENAI_CODEX_MODEL_CODEX,
    }
