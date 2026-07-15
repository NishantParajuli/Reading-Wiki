from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import time
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import AgyCanceled, AgyError, classify_failure
from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import cli_state_path
from novelwiki.platform.config import settings
from novelwiki.platform.observability.logging import log_context, log_event

logger = logging.getLogger(__name__)


CancelCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class RunnerResult:
    exit_code: int
    stdout_tail: str
    stderr_tail: str
    stdout_bytes: int
    stderr_bytes: int
    timed_out: bool
    canceled: bool
    process_group_id: int | None
    process_started_at: str | None
    model_requests: int
    tool_confirmations: int
    sandbox_blocks: int
    hook_failures: int
    empty_planner_responses: int
    hooks_loaded: int | None
    hook_files_loaded: int | None

    def metrics(self) -> dict:
        return {
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "agy_model_requests": self.model_requests,
            "agy_tool_confirmations": self.tool_confirmations,
            "agy_sandbox_blocks": self.sandbox_blocks,
            "agy_hook_failures": self.hook_failures,
            "agy_empty_planner_responses": self.empty_planner_responses,
            "agy_hooks_loaded": self.hooks_loaded,
            "agy_hook_files_loaded": self.hook_files_loaded,
            # AGY print mode does not expose provider token counts.
            "agy_token_usage_available": False,
        }


@dataclass(frozen=True)
class AgyLogTelemetry:
    model_requests: int = 0
    tool_confirmations: int = 0
    sandbox_blocks: int = 0
    hook_failures: int = 0
    empty_planner_responses: int = 0
    hooks_loaded: int | None = None
    hook_files_loaded: int | None = None

    def metrics(self) -> dict:
        return {
            "agy_model_requests": self.model_requests,
            "agy_tool_confirmations": self.tool_confirmations,
            "agy_sandbox_blocks": self.sandbox_blocks,
            "agy_hook_failures": self.hook_failures,
            "agy_empty_planner_responses": self.empty_planner_responses,
            "agy_hooks_loaded": self.hooks_loaded,
            "agy_hook_files_loaded": self.hook_files_loaded,
            "agy_token_usage_available": False,
        }


_HOOKS_RE = re.compile(r"loaded\s+(\d+)\s+named hooks from\s+(\d+)\s+hooks\.json file")


def read_agy_log_telemetry(run_root: Path) -> AgyLogTelemetry:
    """Parse metadata counters only; never retain provider or story log content."""
    try:
        text = (run_root / "logs" / "agy.log").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return AgyLogTelemetry()
    hook_matches = list(_HOOKS_RE.finditer(text))
    hooks_loaded = hook_files = None
    if hook_matches:
        hooks_loaded = int(hook_matches[-1].group(1))
        hook_files = int(hook_matches[-1].group(2))
    return AgyLogTelemetry(
        model_requests=text.count("streamGenerateContent?"),
        tool_confirmations=text.count("Auto-approving tool confirmation:"),
        sandbox_blocks=text.count("SANDBOX_COMMAND_BLOCKED"),
        hook_failures=(
            text.count("pre-tool hook failed:")
            + text.count("failed to call custom stop hook")
            + text.count("error in post-invocation hook:")
        ),
        empty_planner_responses=text.count("PlannerResponse without ModifiedResponse encountered"),
        hooks_loaded=hooks_loaded,
        hook_files_loaded=hook_files,
    )


def _output_progress_marker(run_root: Path) -> tuple[int, int, int]:
    """Return cheap output-tree progress metadata without reading agent content."""
    files = 0
    total_bytes = 0
    latest_mtime_ns = 0
    try:
        paths = (run_root / "output").rglob("*")
        for path in paths:
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError:
                continue
            if path.is_file() and not path.is_symlink():
                files += 1
                total_bytes += stat.st_size
                latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
    except OSError:
        pass
    return files, total_bytes, latest_mtime_ns


def _runner_event(run_root: Path, event: str, **data) -> None:
    """Private metadata-only lifecycle log (never prompt/source/output text)."""
    record = {"at": datetime.now(UTC).isoformat(), "event": event, **data}
    path = run_root / "logs" / "runner.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def child_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Construct the AGY child env from a positive allowlist.

    In particular this never copies DATABASE_URL, provider keys, OAuth secrets,
    cookie/session material, SMTP credentials, or arbitrary *_TOKEN variables.
    """
    source = source or os.environ
    allowed_exact = {
        "HOME", "PATH", "LANG", "TZ", "TMPDIR", "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY",
    }
    env = {k: v for k, v in source.items() if k in allowed_exact or k.startswith("LC_")}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.setdefault("LANG", "C.UTF-8")
    env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    env["AGY_CLI_HIDE_ACCOUNT_INFO"] = "true"
    return env


def _proc_start_time(pid: int) -> str | None:
    try:
        # Field 22, but the process name may contain spaces/parentheses. Split only
        # after the final ')', then index relative to field 3.
        text = Path(f"/proc/{pid}/stat").read_text()
        tail = text[text.rfind(")") + 2:].split()
        return tail[19]
    except (OSError, IndexError):
        return None


def process_identity_matches(pid: int, started_at: str | None) -> bool:
    return bool(started_at and _proc_start_time(pid) == started_at)


async def terminate_process_group(pgid: int | None, *, started_at: str | None = None) -> None:
    if not pgid or (started_at is not None and not process_identity_matches(pgid, started_at)):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = asyncio.get_running_loop().time() + settings.AGY_KILL_GRACE_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        alive = process_identity_matches(pgid, started_at) if started_at else Path(f"/proc/{pgid}").exists()
        if not alive:
            return
        await asyncio.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def _drain(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, int]:
    tail = bytearray()
    total = 0
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        tail.extend(chunk)
        if len(tail) > cap:
            del tail[:-cap]
    return bytes(tail), total


def build_argv(run_root: Path, prompt: str, model: str) -> list[str]:
    argv = [
        settings.AGY_BINARY,
        f"--gemini_dir={cli_state_path(run_root)}",
        "--new-project",
        "--print", prompt,
        "--model", model,
        "--sandbox",
        "--print-timeout", f"{settings.AGY_PRINT_TIMEOUT_SECONDS}s",
        "--log-file", str(run_root / "logs" / "agy.log"),
    ]
    if settings.AGY_MODE:
        argv.extend(["--mode", settings.AGY_MODE])
    return argv


async def run_agy(
    run_root: Path,
    *,
    prompt: str,
    model: str,
    cancel_check: CancelCheck | None = None,
    on_spawn: Callable[[int, str | None], Awaitable[None]] | None = None,
) -> RunnerResult:
    argv = build_argv(run_root, prompt, model)
    started_monotonic = time.monotonic()
    run_id = run_root.name
    with log_context(ai_run_id=run_id):
        log_event(
            logger, logging.INFO, "agy.process_starting",
            f"Starting AGY subprocess for run {run_id} with model {model}.",
            model=model, binary=Path(settings.AGY_BINARY).name,
            print_timeout_seconds=settings.AGY_PRINT_TIMEOUT_SECONDS,
            outer_grace_seconds=settings.AGY_OUTER_TIMEOUT_GRACE_SECONDS,
            mode=settings.AGY_MODE or "default", sandbox=True,
        )
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=run_root,
            env=child_environment(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except Exception:
        with log_context(ai_run_id=run_id):
            log_event(
                logger, logging.ERROR, "agy.process_spawn_failed",
                f"Could not spawn the AGY subprocess for run {run_id}.",
                exc_info=True, model=model, binary=Path(settings.AGY_BINARY).name,
                duration_ms=round((time.monotonic() - started_monotonic) * 1000, 2),
            )
        raise
    pgid = process.pid
    started_at = _proc_start_time(process.pid)
    stdout_task = asyncio.create_task(_drain(process.stdout, settings.AGY_STDOUT_MAX_BYTES))
    stderr_task = asyncio.create_task(_drain(process.stderr, settings.AGY_STDERR_MAX_BYTES))
    try:
        pgid_file = run_root / "logs" / "agy.pgid"
        pgid_file.write_text(json.dumps({"pgid": pgid, "started_at": started_at}), encoding="utf-8")
        os.chmod(pgid_file, 0o600)
        if on_spawn:
            await on_spawn(pgid, started_at)
        _runner_event(run_root, "spawned", pid=pgid, model=model,
                      binary=Path(settings.AGY_BINARY).name,
                      flags=["new-project", "print", "model", "sandbox", "print-timeout", "log-file"] + (["mode"] if settings.AGY_MODE else []))
        with log_context(ai_run_id=run_id):
            log_event(
                logger, logging.INFO, "agy.process_spawned",
                f"Spawned AGY subprocess {pgid} for run {run_id}.",
                process_group_id=pgid, process_started_at=started_at, model=model,
                binary=Path(settings.AGY_BINARY).name,
            )

        deadline = asyncio.get_running_loop().time() + settings.AGY_PRINT_TIMEOUT_SECONDS + settings.AGY_OUTER_TIMEOUT_GRACE_SECONDS
        timed_out = canceled = request_limited = plugin_inactive = hook_failed = planner_loop = False
        output_marker = _output_progress_marker(run_root)
        planner_responses_at_progress = 0
        while process.returncode is None:
            telemetry = read_agy_log_telemetry(run_root)
            current_output_marker = _output_progress_marker(run_root)
            if current_output_marker != output_marker:
                output_marker = current_output_marker
                planner_responses_at_progress = telemetry.empty_planner_responses
            if (
                telemetry.hooks_loaded is not None
                and (
                    telemetry.hooks_loaded != settings.AGY_REQUIRED_LOADED_HOOKS
                    or telemetry.hook_files_loaded != 1
                )
            ):
                plugin_inactive = True
                await terminate_process_group(pgid, started_at=started_at)
                break
            if (
                telemetry.empty_planner_responses - planner_responses_at_progress
                > settings.AGY_MAX_EMPTY_PLANNER_RESPONSES
            ):
                planner_loop = True
                await terminate_process_group(pgid, started_at=started_at)
                break
            if telemetry.model_requests > settings.AGY_MAX_MODEL_REQUESTS_PER_RUN:
                request_limited = True
                await terminate_process_group(pgid, started_at=started_at)
                break
            if telemetry.hook_failures:
                hook_failed = True
                await terminate_process_group(pgid, started_at=started_at)
                break
            if cancel_check and await cancel_check():
                canceled = True
                await terminate_process_group(pgid, started_at=started_at)
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                timed_out = True
                await terminate_process_group(pgid, started_at=started_at)
                break
            try:
                await asyncio.wait_for(process.wait(), timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
                continue
    except BaseException as exc:
        if process.returncode is None:
            await terminate_process_group(pgid, started_at=started_at)
        await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        _runner_event(run_root, "monitor_error", error_type=type(exc).__name__, exit_code=process.returncode)
        with log_context(ai_run_id=run_id):
            log_event(
                logger, logging.ERROR, "agy.process_monitor_failed",
                f"AGY subprocess monitoring failed for run {run_id}.",
                exc_info=True, process_group_id=pgid, exit_code=process.returncode,
                duration_ms=round((time.monotonic() - started_monotonic) * 1000, 2),
            )
        raise
    await process.wait()
    stdout_data, stdout_bytes = await stdout_task
    stderr_data, stderr_bytes = await stderr_task
    telemetry = read_agy_log_telemetry(run_root)
    result = RunnerResult(
        int(process.returncode), stdout_data.decode("utf-8", "replace"),
        stderr_data.decode("utf-8", "replace"), stdout_bytes, stderr_bytes,
        timed_out, canceled, pgid, started_at,
        telemetry.model_requests, telemetry.tool_confirmations,
        telemetry.sandbox_blocks, telemetry.hook_failures,
        telemetry.empty_planner_responses, telemetry.hooks_loaded,
        telemetry.hook_files_loaded,
    )
    _runner_event(run_root, "exited", exit_code=result.exit_code, timed_out=timed_out,
                  canceled=canceled, stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes)
    with log_context(ai_run_id=run_id):
        exit_level = logging.ERROR if (timed_out or (result.exit_code != 0 and not canceled)) else (
            logging.WARNING if canceled else logging.INFO
        )
        log_event(
            logger, exit_level, "agy.process_exited",
            f"AGY subprocess for run {run_id} exited with code {result.exit_code}.",
            process_group_id=pgid, exit_code=result.exit_code,
            timed_out=timed_out, canceled=canceled,
            stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes,
            **telemetry.metrics(),
            stdout_truncated=stdout_bytes > settings.AGY_STDOUT_MAX_BYTES,
            stderr_truncated=stderr_bytes > settings.AGY_STDERR_MAX_BYTES,
            duration_ms=round((time.monotonic() - started_monotonic) * 1000, 2),
        )
    if canceled:
        raise AgyCanceled("AGY run was canceled")
    if plugin_inactive or (
        result.hooks_loaded is None
        or result.hooks_loaded != settings.AGY_REQUIRED_LOADED_HOOKS
        or result.hook_files_loaded != 1
    ):
        raise AgyError(
            "AGY did not load the required NovelWiki safety hooks",
            code="agy_plugin_inactive", retryable=False, metrics=result.metrics(),
        )
    if planner_loop:
        raise AgyError(
            "AGY returned repeated planner responses without output progress",
            code="agy_planner_loop", retryable=False, metrics=result.metrics(),
        )
    if request_limited or result.model_requests > settings.AGY_MAX_MODEL_REQUESTS_PER_RUN:
        raise AgyError(
            "AGY exceeded the configured per-run model-request ceiling",
            code="agy_request_limit", retryable=False, metrics=result.metrics(),
        )
    if hook_failed or result.hook_failures:
        raise AgyError(
            "an AGY NovelWiki lifecycle hook failed",
            code="agy_hook_failure", retryable=False, metrics=result.metrics(),
        )
    if timed_out:
        raise AgyError(
            "AGY exceeded its outer timeout", code="agy_timeout", metrics=result.metrics()
        )
    if result.exit_code != 0:
        code = classify_failure(result.stderr_tail, exit_code=result.exit_code)
        retryable = code not in {"agy_not_authenticated", "agy_permission_blocked"}
        raise AgyError(
            f"AGY exited nonzero ({result.exit_code})", code=code,
            retryable=retryable, metrics=result.metrics(),
        )
    return result
