from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from novelwiki.modules.ai_execution.application.errors import AgyCanceled, AgyError
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.workspace import (
    codex_home_path,
)
from novelwiki.platform.config import settings


CancelCheck = Callable[[], Awaitable[bool]]


def child_environment(run_root: Path, source: dict[str, str] | None = None) -> dict[str, str]:
    """Build a positive-allowlist environment with isolated Codex state."""
    source = source or os.environ
    allowed = {"HOME", "PATH", "LANG", "TZ", "TMPDIR"}
    env = {key: value for key, value in source.items() if key in allowed or key.startswith("LC_")}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.setdefault("LANG", "C.UTF-8")
    env["CODEX_HOME"] = str(codex_home_path(run_root))
    env["CODEX_CLI_DISABLE_AUTO_UPDATE"] = "1"
    return env


def _proc_start_time(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        tail = text[text.rfind(")") + 2 :].split()
        return tail[19]
    except (OSError, IndexError):
        return None


def process_identity_matches(pid: int, started_at: str | None) -> bool:
    return bool(started_at and _proc_start_time(pid) == started_at)


async def terminate_process_group(
    pgid: int | None, *, started_at: str | None = None
) -> None:
    if not pgid or (started_at is not None and not process_identity_matches(pgid, started_at)):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = asyncio.get_running_loop().time() + settings.OPENAI_CODEX_KILL_GRACE_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        if started_at and not process_identity_matches(pgid, started_at):
            return
        await asyncio.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def _drain(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, int]:
    tail = bytearray()
    total = 0
    while chunk := await stream.read(65_536):
        total += len(chunk)
        tail.extend(chunk)
        if len(tail) > cap:
            del tail[:-cap]
    return bytes(tail), total


@dataclass
class AppServerResult:
    value: dict[str, Any]
    exit_code: int = 0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    process_group_id: int | None = None
    process_started_at: str | None = None
    token_usage: dict[str, Any] = field(default_factory=dict)
    thread_id: str | None = None
    turn_id: str | None = None

    def metrics(self) -> dict[str, Any]:
        usage = self.token_usage.get("last") or self.token_usage.get("total") or {}
        return {
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "openai_codex_input_tokens": int(usage.get("inputTokens") or 0),
            "openai_codex_cached_input_tokens": int(usage.get("cachedInputTokens") or 0),
            "openai_codex_output_tokens": int(usage.get("outputTokens") or 0),
            "openai_codex_reasoning_output_tokens": int(
                usage.get("reasoningOutputTokens") or 0
            ),
            "openai_codex_total_tokens": int(usage.get("totalTokens") or 0),
            "openai_codex_token_usage_available": bool(usage),
            "openai_codex_thread_id": self.thread_id,
            "openai_codex_turn_id": self.turn_id,
        }


class AppServerSession:
    def __init__(self, run_root: Path):
        self.run_root = run_root
        self.process: asyncio.subprocess.Process | None = None
        self.stderr_task: asyncio.Task | None = None
        self.stderr_tail = b""
        self.stderr_bytes = 0
        self.stdout_bytes = 0
        self._request_id = 0
        self._token_usage: dict[str, Any] = {}
        self._agent_message: str | None = None

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            settings.OPENAI_CODEX_BINARY,
            "app-server",
            "--stdio",
            "--strict-config",
            cwd=self.run_root,
            env=child_environment(self.run_root),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=settings.OPENAI_CODEX_STDOUT_MAX_BYTES + 1,
        )
        self.stderr_task = asyncio.create_task(
            _drain(self.process.stderr, settings.OPENAI_CODEX_STDERR_MAX_BYTES)
        )

    async def _send(self, value: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Codex App Server is not running")
        self.process.stdin.write(
            (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        )
        await self.process.stdin.drain()

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        await self._send(message)

    async def _read(self) -> dict[str, Any]:
        if not self.process or not self.process.stdout:
            raise RuntimeError("Codex App Server is not running")
        try:
            line = await self.process.stdout.readline()
        except (ValueError, asyncio.LimitOverrunError) as exc:
            raise AgyError(
                "Codex App Server emitted an oversized JSONL message",
                code="openai_codex_protocol_error",
                retryable=False,
            ) from exc
        if not line:
            raise AgyError(
                "Codex App Server exited before completing the request",
                code="openai_codex_app_server_exited",
            )
        self.stdout_bytes += len(line)
        if self.stdout_bytes > settings.OPENAI_CODEX_STDOUT_MAX_BYTES:
            raise AgyError(
                "Codex App Server exceeded the output retention limit",
                code="openai_codex_protocol_error",
                retryable=False,
            )
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgyError(
                "Codex App Server emitted invalid JSONL",
                code="openai_codex_protocol_error",
                retryable=False,
            ) from exc
        if not isinstance(value, dict):
            raise AgyError(
                "Codex App Server emitted a non-object message",
                code="openai_codex_protocol_error",
                retryable=False,
            )
        return value

    def _observe(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "thread/tokenUsage/updated":
            self._token_usage = params.get("tokenUsage") or {}
        elif method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "agentMessage":
                self._agent_message = item.get("text")

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        cancel_check: CancelCheck | None = None,
        timeout: float = 30,
    ) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        await self._send({"id": request_id, "method": method, "params": params})
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if cancel_check and await cancel_check():
                raise AgyCanceled("OpenAI Codex run canceled", code="openai_codex_canceled")
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AgyError(
                    f"Codex App Server timed out waiting for {method}",
                    code="openai_codex_timeout",
                )
            try:
                message = await asyncio.wait_for(self._read(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            self._observe(message)
            if "id" in message and message.get("id") != request_id:
                raise AgyError(
                    "Codex App Server response ID did not match the active request",
                    code="openai_codex_protocol_error",
                    retryable=False,
                )
            if message.get("id") == request_id:
                if message.get("error") is not None:
                    raise AgyError(
                        "Codex App Server rejected the request",
                        code="openai_codex_request_failed",
                    )
                result = message.get("result")
                if not isinstance(result, dict):
                    raise AgyError(
                        "Codex App Server returned an invalid response",
                        code="openai_codex_protocol_error",
                        retryable=False,
                    )
                return result
            if "id" in message and "method" in message:
                raise AgyError(
                    "Codex App Server requested an interactive client action",
                    code="openai_codex_permission_blocked",
                    retryable=False,
                )

    async def initialize(self) -> None:
        await self.request(
            "initialize",
            {
                "clientInfo": {"name": "novelwiki", "title": "NovelWiki", "version": "1"},
                "capabilities": {"experimentalApi": False},
            },
        )
        await self.notify("initialized")

    async def run_turn(
        self,
        *,
        model: str,
        effort: str,
        developer_instructions: str,
        user_input: str,
        output_schema: dict[str, Any],
        cancel_check: CancelCheck | None = None,
    ) -> AppServerResult:
        thread_result = await self.request(
            "thread/start",
            {
                "model": model,
                "cwd": str(self.run_root),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
                "developerInstructions": developer_instructions,
            },
            cancel_check=cancel_check,
        )
        thread_id = str((thread_result.get("thread") or {}).get("id") or "")
        if not thread_id:
            raise AgyError(
                "Codex App Server did not return a thread ID",
                code="openai_codex_protocol_error",
                retryable=False,
            )
        turn_result = await self.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": user_input}],
                "model": model,
                "effort": effort,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "outputSchema": output_schema,
            },
            cancel_check=cancel_check,
        )
        turn_id = str((turn_result.get("turn") or {}).get("id") or "")
        deadline = asyncio.get_running_loop().time() + settings.OPENAI_CODEX_TURN_TIMEOUT_SECONDS
        while True:
            if cancel_check and await cancel_check():
                try:
                    await self.request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": turn_id},
                        timeout=5,
                    )
                finally:
                    raise AgyCanceled(
                        "OpenAI Codex run canceled", code="openai_codex_canceled"
                    )
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AgyError("OpenAI Codex turn timed out", code="openai_codex_timeout")
            try:
                message = await asyncio.wait_for(self._read(), timeout=min(0.5, remaining))
            except asyncio.TimeoutError:
                continue
            self._observe(message)
            if "id" in message and "method" in message:
                raise AgyError(
                    "Codex attempted an interactive or external tool action",
                    code="openai_codex_permission_blocked",
                    retryable=False,
                )
            if message.get("method") != "turn/completed":
                continue
            turn = (message.get("params") or {}).get("turn") or {}
            status = turn.get("status")
            if status != "completed":
                error = turn.get("error") or {}
                info = str(error.get("codexErrorInfo") or error.get("message") or status)
                lowered = info.lower()
                code = (
                    "openai_codex_quota_likely_exhausted"
                    if "usage" in lowered or "limit" in lowered
                    else "openai_codex_provider_unavailable"
                    if "overloaded" in lowered or "connection" in lowered
                    else "openai_codex_turn_failed"
                )
                raise AgyError("OpenAI Codex turn failed", code=code)
            if not self._agent_message:
                raise AgyError(
                    "OpenAI Codex completed without a final message",
                    code="openai_codex_empty_output",
                )
            try:
                value = json.loads(self._agent_message)
            except json.JSONDecodeError as exc:
                raise AgyError(
                    "OpenAI Codex final message was not JSON",
                    code="openai_codex_artifact_invalid",
                    retryable=False,
                ) from exc
            if not isinstance(value, dict):
                raise AgyError(
                    "OpenAI Codex final JSON was not an object",
                    code="openai_codex_artifact_invalid",
                    retryable=False,
                )
            return AppServerResult(
                value=value,
                stdout_bytes=self.stdout_bytes,
                stderr_bytes=self.stderr_bytes,
                process_group_id=self.process.pid if self.process else None,
                process_started_at=(
                    _proc_start_time(self.process.pid) if self.process else None
                ),
                token_usage=self._token_usage,
                thread_id=thread_id,
                turn_id=turn_id,
            )

    async def close(self) -> tuple[int, str, int]:
        if not self.process:
            return 0, "", 0
        if self.process.stdin:
            self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=2)
        except asyncio.TimeoutError:
            await terminate_process_group(
                self.process.pid, started_at=_proc_start_time(self.process.pid)
            )
            await self.process.wait()
        if self.stderr_task:
            self.stderr_tail, self.stderr_bytes = await self.stderr_task
        return self.process.returncode or 0, self.stderr_tail.decode(errors="replace"), self.stderr_bytes

