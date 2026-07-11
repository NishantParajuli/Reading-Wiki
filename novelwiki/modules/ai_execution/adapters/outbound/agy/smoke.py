from __future__ import annotations

from datetime import UTC, datetime

from novelwiki.modules.ai_execution.adapters.outbound.agy.contracts import InputManifest
from novelwiki.modules.ai_execution.adapters.outbound.agy.preflight import run_preflight
from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import safe_error_summary
from novelwiki.modules.ai_execution.adapters.outbound.agy.runner import run_agy
from novelwiki.modules.ai_execution.adapters.outbound.agy.runs import create_run, update_run, workspace_relpath
from novelwiki.modules.ai_execution.adapters.outbound.agy.validators import read_text_artifact, validate_output_manifest
from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import add_input, create_run_workspace, seal_inputs, sha256_file, write_json
from novelwiki.platform.config import settings
from novelwiki.modules.work.public import service


async def run_smoke_test(job_id: int) -> dict:
    """Explicit consuming admin smoke test with no novel/user content."""
    preflight = await run_preflight()
    job = await service.get_job(job_id)
    if not job:
        raise RuntimeError("smoke job no longer exists")
    run_id = await create_run(
        job=job, workload="smoke_test", model=settings.AGY_MODEL_TRANSLATE,
        runner_version=preflight.version, plugin_version=settings.AGY_PLUGIN_VERSION,
        plugin_sha256=preflight.plugin_sha256 or "",
    )
    root = create_run_workspace(job_id, str(run_id))
    payload = b"Write exactly the word READY followed by a newline to the contracted smoke artifact.\n"
    inputs = [add_input(root, "smoke.txt", payload, role="smoke_input",
                        media_type="text/plain; charset=utf-8")]
    manifest = InputManifest(
        run_id=str(run_id), job_id=job_id, workload="smoke_test",
        plugin_version=settings.AGY_PLUGIN_VERSION, model=settings.AGY_MODEL_TRANSLATE,
        novel_ref="none", inputs=inputs, limits={"output_bytes": 64}, created_at=datetime.now(UTC),
    )
    write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json"))
    seal_inputs(root)
    await update_run(run_id, status="running", input_sha256=sha256_file(root / "input" / "manifest.json"),
                     workspace_relpath=workspace_relpath(root), started_at=datetime.now(UTC))
    try:
        result = await run_agy(
            root, prompt="Run novelwiki-smoke for input/manifest.json and write the output manifest last.",
            model=settings.AGY_MODEL_TRANSLATE,
            cancel_check=lambda: service.is_canceled(job_id),
            on_spawn=lambda pgid, started: update_run(run_id, process_group_id=pgid, process_started_at=started),
        )
        output_manifest, roles = validate_output_manifest(
            root, run_id=str(run_id), workload="smoke_test", expected_roles={"smoke": 1},
        )
        smoke_hash = next(ref.sha256 for ref in output_manifest.artifacts if ref.role == "smoke")
        if read_text_artifact(roles["smoke"][0], expected_sha256=smoke_hash).strip() != "READY":
            raise RuntimeError("AGY smoke artifact did not contain READY")
        await update_run(run_id, status="completed", output_sha256=sha256_file(root / "output" / "manifest.json"),
                         exit_code=result.exit_code, finished_at=datetime.now(UTC),
                         metrics={"stdout_bytes": result.stdout_bytes, "stderr_bytes": result.stderr_bytes})
    except Exception as exc:
        await update_run(run_id, status="failed", failure_code=getattr(exc, "code", "unknown"),
                         error_summary=safe_error_summary(exc), finished_at=datetime.now(UTC))
        raise
    return {"status": "success", "version": preflight.version, "model": settings.AGY_MODEL_TRANSLATE,
            "plugin_version": settings.AGY_PLUGIN_VERSION, "duration_observed": True,
            "stdout_bytes": result.stdout_bytes, "stderr_bytes": result.stderr_bytes}
