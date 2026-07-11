from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import AgyCanceled, AgyError, classify_failure
from novelwiki.platform.config import settings


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
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=run_root,
        env=child_environment(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
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
                      flags=["print", "model", "sandbox", "print-timeout", "log-file"] + (["mode"] if settings.AGY_MODE else []))

        deadline = asyncio.get_running_loop().time() + settings.AGY_PRINT_TIMEOUT_SECONDS + settings.AGY_OUTER_TIMEOUT_GRACE_SECONDS
        timed_out = canceled = False
        while process.returncode is None:
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
        raise
    await process.wait()
    stdout_data, stdout_bytes = await stdout_task
    stderr_data, stderr_bytes = await stderr_task
    result = RunnerResult(
        int(process.returncode), stdout_data.decode("utf-8", "replace"),
        stderr_data.decode("utf-8", "replace"), stdout_bytes, stderr_bytes,
        timed_out, canceled, pgid, started_at,
    )
    _runner_event(run_root, "exited", exit_code=result.exit_code, timed_out=timed_out,
                  canceled=canceled, stdout_bytes=stdout_bytes, stderr_bytes=stderr_bytes)
    if canceled:
        raise AgyCanceled("AGY run was canceled")
    if timed_out:
        raise AgyError("AGY exceeded its outer timeout", code="agy_timeout")
    if result.exit_code != 0:
        code = classify_failure(result.stderr_tail, exit_code=result.exit_code)
        retryable = code not in {"agy_not_authenticated", "agy_permission_blocked"}
        raise AgyError(f"AGY exited nonzero ({result.exit_code})", code=code, retryable=retryable)
    return result
