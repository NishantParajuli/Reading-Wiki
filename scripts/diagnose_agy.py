#!/usr/bin/env python3
"""Run bounded, disposable Antigravity CLI compatibility probes.

This script deliberately does not use a NovelWiki job workspace or database. Each
probe receives an isolated CLI state directory, a tiny temporary Git repository,
and strict request/time ceilings. The JSON result contains counters and the fixed
probe result only; AGY's potentially sensitive raw log is deleted with the temp
directory unless --keep is supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_BINARY = Path.home() / ".local" / "bin" / "agy"
DEFAULT_CREDENTIAL_DIR = Path.home() / ".gemini" / "antigravity-cli"
DEFAULT_MODEL = "Gemini 3.5 Flash (Medium)"


@dataclass(frozen=True)
class ProbeResult:
    scenario: str
    model: str
    mode: str
    tool_permission: str
    artifact_review_policy: str
    sandbox: bool
    exit_code: int
    termination: str
    duration_seconds: float
    model_requests: int
    empty_planner_responses: int
    tool_confirmations: int
    sandbox_blocks: int
    hooks_loaded: int
    stdout_bytes: int
    stderr_bytes: int
    output_ok: bool
    retained_root: str | None


def _read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _count_telemetry(log: str) -> dict[str, int]:
    return {
        "model_requests": log.count("streamGenerateContent?"),
        "empty_planner_responses": log.count(
            "PlannerResponse without ModifiedResponse encountered"
        ),
        "tool_confirmations": log.count("Auto-approving tool confirmation:"),
        "sandbox_blocks": log.count("SANDBOX_COMMAND_BLOCKED"),
        "hooks_loaded": log.count("Loaded hook") + log.count("registered hook"),
    }


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def _prepare_state(
    root: Path,
    workspace: Path,
    credential_dir: Path,
    *,
    mode: str,
    tool_permission: str,
    artifact_review_policy: str,
) -> Path:
    state = root / "state"
    cli_dir = state / "antigravity-cli"
    cli_dir.mkdir(parents=True, mode=0o700)

    token = credential_dir / "antigravity-oauth-token"
    if not token.is_file():
        raise FileNotFoundError(f"AGY credential is missing: {token}")
    os.symlink(token, cli_dir / token.name)

    installation_id = credential_dir / "installation_id"
    if installation_id.is_file():
        os.symlink(installation_id, cli_dir / installation_id.name)

    source_settings = credential_dir / "settings.json"
    settings: dict[str, object] = {}
    if source_settings.is_file():
        settings = json.loads(source_settings.read_text(encoding="utf-8"))
    settings["trustedWorkspaces"] = [str(workspace)]
    if mode:
        settings["agentMode"] = mode
    else:
        settings.pop("agentMode", None)
    if tool_permission:
        settings["toolPermission"] = tool_permission
    else:
        settings.pop("toolPermission", None)
    if artifact_review_policy:
        settings["artifactReviewPolicy"] = artifact_review_policy
    else:
        settings.pop("artifactReviewPolicy", None)
    target = cli_dir / "settings.json"
    target.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    target.chmod(0o600)
    return state


def run_probe(args: argparse.Namespace) -> ProbeResult:
    retained_root: str | None = None
    temp = tempfile.mkdtemp(prefix="novelwiki-agy-probe-")
    root = Path(temp)
    if args.keep:
        retained_root = temp
    try:
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        subprocess.run(
            ["git", "init", "-q", str(workspace)],
            check=True,
            stdin=subprocess.DEVNULL,
        )
        state = _prepare_state(
            root,
            workspace,
            args.credential_dir,
            mode=args.mode,
            tool_permission=args.tool_permission,
            artifact_review_policy=args.artifact_review_policy,
        )
        log_path = root / "agy.log"
        stdout_path = root / "stdout"
        stderr_path = root / "stderr"

        if args.scenario == "text":
            prompt = "Reply with exactly READY and do not use tools."
        else:
            prompt = (
                "Create result.txt in the current workspace containing exactly READY "
                "followed by one newline. Do not use the terminal or create other files."
            )

        argv = [
            str(args.binary),
            f"--gemini_dir={state}",
            "--new-project",
            "--print",
            prompt,
            "--model",
            args.model,
            "--print-timeout",
            f"{args.timeout}s",
            "--log-file",
            str(log_path),
        ]
        if args.mode:
            argv.extend(["--mode", args.mode])
        if args.sandbox:
            argv.append("--sandbox")

        env = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "HOME",
                "PATH",
                "LANG",
                "TZ",
                "TMPDIR",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                "DISPLAY",
                "WAYLAND_DISPLAY",
            }
            or key.startswith("LC_")
        }
        env.update(
            {
                "AGY_CLI_DISABLE_AUTO_UPDATE": "true",
                "AGY_CLI_HIDE_ACCOUNT_INFO": "true",
            }
        )
        started = time.monotonic()
        termination = "exited"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            while process.poll() is None:
                log = _read_log(log_path)
                counts = _count_telemetry(log)
                if counts["model_requests"] > args.max_requests:
                    termination = "request_limit"
                    _terminate_group(process)
                    break
                if time.monotonic() - started > args.timeout + 5:
                    termination = "outer_timeout"
                    _terminate_group(process)
                    break
                time.sleep(0.25)
            exit_code = int(process.wait())

        duration = time.monotonic() - started
        counts = _count_telemetry(_read_log(log_path))
        stdout_data = stdout_path.read_bytes()
        stderr_data = stderr_path.read_bytes()
        if args.scenario == "text":
            output_ok = stdout_data.decode("utf-8", "replace").strip() == "READY"
        else:
            result_path = workspace / "result.txt"
            output_ok = result_path.is_file() and result_path.read_bytes() == b"READY\n"
        return ProbeResult(
            scenario=args.scenario,
            model=args.model,
            mode=args.mode or "default",
            tool_permission=args.tool_permission or "default",
            artifact_review_policy=args.artifact_review_policy or "default",
            sandbox=args.sandbox,
            exit_code=exit_code,
            termination=termination,
            duration_seconds=round(duration, 3),
            stdout_bytes=len(stdout_data),
            stderr_bytes=len(stderr_data),
            output_ok=output_ok,
            retained_root=retained_root,
            **counts,
        )
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument(
        "--credential-dir", type=Path, default=DEFAULT_CREDENTIAL_DIR
    )
    parser.add_argument("--scenario", choices=("text", "write"), default="text")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--mode", choices=("", "accept-edits", "plan"), default="")
    parser.add_argument(
        "--tool-permission",
        choices=("", "request-review", "proceed-in-sandbox", "always-proceed", "strict"),
        default="",
    )
    parser.add_argument(
        "--artifact-review-policy",
        choices=("", "asks-for-review", "agent-decides", "always-proceed"),
        default="",
    )
    parser.add_argument("--sandbox", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--keep", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(asdict(run_probe(parse_args())), sort_keys=True))
