from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import stat
import uuid
from pathlib import Path

from novelwiki.modules.ai_execution.application.contracts import PreflightResult
from novelwiki.modules.ai_execution.application.errors import AgyPreflightError
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.client import (
    AppServerSession,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.runner import (
    contract_sha256,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.workspace import (
    codex_home_path,
    create_run_workspace,
    validate_credential_dir,
    validate_work_root,
)
from novelwiki.platform.config import settings


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", value or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def validate_binary() -> tuple[Path, str]:
    path = Path(settings.OPENAI_CODEX_BINARY).expanduser()
    if not path.is_absolute() or not path.exists():
        raise AgyPreflightError(
            "Codex is not installed at OPENAI_CODEX_BINARY",
            code="openai_codex_not_installed",
        )
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or not os.access(path, os.X_OK):
        raise AgyPreflightError(
            "OPENAI_CODEX_BINARY is not a regular executable",
            code="openai_codex_not_installed",
        )
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise AgyPreflightError(
            "Codex executable must not be group/world-writable",
            code="openai_codex_version_unsupported",
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if (
        settings.OPENAI_CODEX_BINARY_SHA256
        and digest != settings.OPENAI_CODEX_BINARY_SHA256.lower()
    ):
        raise AgyPreflightError(
            "Codex executable hash differs from OPENAI_CODEX_BINARY_SHA256",
            code="openai_codex_version_unsupported",
        )
    return path, digest


async def _version(path: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        str(path),
        "--version",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise AgyPreflightError(
            "Codex version probe timed out",
            code="openai_codex_provider_unavailable",
        ) from exc
    if process.returncode:
        raise AgyPreflightError(
            "Codex version probe failed",
            code="openai_codex_version_unsupported",
        )
    text = stdout.decode(errors="replace").strip() or stderr.decode(errors="replace").strip()
    return text.splitlines()[0] if text else ""


async def run_preflight(*, raise_on_error: bool = True) -> PreflightResult:
    version = digest = None
    models: tuple[str, ...] = ()
    contract_hash = contract_sha256()
    run_root: Path | None = None
    try:
        path, digest = validate_binary()
        validate_credential_dir()
        work_root = validate_work_root()
        work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(work_root, 0o700)
        version = await _version(path)
        if _version_tuple(version) < _version_tuple(settings.OPENAI_CODEX_MIN_VERSION):
            raise AgyPreflightError(
                f"Codex {version} is older than {settings.OPENAI_CODEX_MIN_VERSION}",
                code="openai_codex_version_unsupported",
            )

        run_root = create_run_workspace(0, f"preflight-{uuid.uuid4().hex}")
        session = AppServerSession(run_root)
        try:
            await session.start()
            await session.initialize()
            account = await session.request(
                "account/read", {"refreshToken": False}, timeout=20
            )
            account_data = account.get("account") or {}
            if account_data.get("type") != "chatgpt":
                raise AgyPreflightError(
                    "Codex worker is not authenticated with a ChatGPT subscription",
                    code="openai_codex_not_authenticated",
                )
            response = await session.request(
                "model/list", {"includeHidden": False, "limit": 100}, timeout=20
            )
            models = tuple(
                str(item.get("model") or item.get("id"))
                for item in response.get("data", [])
                if item.get("model") or item.get("id")
            )
        finally:
            await session.close()
        required = {
            settings.OPENAI_CODEX_MODEL_TRANSLATE,
            settings.OPENAI_CODEX_MODEL_CODEX,
        }
        missing = sorted(required - set(models))
        if missing:
            raise AgyPreflightError(
                f"Configured OpenAI Codex model(s) missing: {', '.join(missing)}",
                code="openai_codex_model_missing",
            )
        return PreflightResult(
            True,
            version,
            digest,
            models,
            settings.OPENAI_CODEX_CONTRACT_VERSION,
            contract_hash,
            True,
        )
    except AgyPreflightError as exc:
        if raise_on_error:
            raise
        return PreflightResult(
            False,
            version,
            digest,
            models,
            settings.OPENAI_CODEX_CONTRACT_VERSION,
            contract_hash,
            False,
            exc.code,
            str(exc),
        )
    except Exception as exc:
        wrapped = AgyPreflightError(
            "OpenAI Codex App Server preflight failed",
            code="openai_codex_provider_unavailable",
        )
        if raise_on_error:
            raise wrapped from exc
        return PreflightResult(
            False,
            version,
            digest,
            models,
            settings.OPENAI_CODEX_CONTRACT_VERSION,
            contract_hash,
            False,
            wrapped.code,
            str(wrapped),
        )
    finally:
        if run_root is not None:
            shutil.rmtree(codex_home_path(run_root), ignore_errors=True)
            shutil.rmtree(run_root, ignore_errors=True)
            try:
                run_root.parent.rmdir()
            except OSError:
                pass


if __name__ == "__main__":
    import json

    result = asyncio.run(run_preflight(raise_on_error=False))
    print(json.dumps(result.public(), indent=2))
    raise SystemExit(0 if result.healthy else 1)
