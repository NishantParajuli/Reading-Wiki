from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from novelwiki.modules.ai_execution.adapters.outbound.agy import PLUGIN_SOURCE
from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import AgyPreflightError
from novelwiki.modules.ai_execution.adapters.outbound.agy.runner import child_environment
from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import (
    provision_cli_state,
    tree_sha256,
    validate_work_root,
)
from novelwiki.modules.ai_execution.application.contracts import PreflightResult
from novelwiki.platform.config import settings


async def _command(
    *argv: str, timeout: float = 20, cwd: Path | None = None,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv, env=child_environment(), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill(); await proc.wait()
        raise AgyPreflightError("AGY preflight command timed out", code="agy_provider_unavailable")
    return proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", value or "")
    if not match:
        return ()
    return tuple(int(x) for x in match.group(1).split("."))


def validate_binary() -> tuple[Path, str]:
    path = Path(settings.AGY_BINARY)
    if not path.is_absolute() or not path.exists():
        raise AgyPreflightError("AGY binary is not installed at the configured absolute path",
                                code="agy_not_installed")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or not os.access(path, os.X_OK):
        raise AgyPreflightError("AGY binary is not a regular executable", code="agy_not_installed")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise AgyPreflightError("AGY binary must not be group/world-writable", code="agy_version_unsupported")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if settings.AGY_BINARY_SHA256 and digest != settings.AGY_BINARY_SHA256.lower():
        raise AgyPreflightError("AGY binary hash differs from the configured integrity pin",
                                code="agy_version_unsupported")
    return path, digest


async def run_preflight(*, raise_on_error: bool = True) -> PreflightResult:
    version = digest = None
    models: tuple[str, ...] = ()
    plugin_hash = None
    probe_state: Path | None = None
    try:
        path, digest = validate_binary()
        work_root = validate_work_root()
        work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(work_root, 0o700)
        if not PLUGIN_SOURCE.is_dir():
            raise AgyPreflightError("NovelWiki AGY plugin source is missing", code="agy_plugin_invalid")
        plugin_hash = tree_sha256(PLUGIN_SOURCE)
        if settings.AGY_PLUGIN_SHA256 and plugin_hash != settings.AGY_PLUGIN_SHA256.lower():
            raise AgyPreflightError("NovelWiki AGY plugin hash differs from its pin", code="agy_plugin_invalid")

        rc, out, err = await _command(str(path), "--version")
        if rc:
            raise AgyPreflightError("AGY version probe failed", code="agy_version_unsupported")
        version = out.strip().splitlines()[0] if out.strip() else err.strip().splitlines()[0]
        if _version_tuple(version) < _version_tuple(settings.AGY_MIN_VERSION):
            raise AgyPreflightError(f"AGY {version} is older than {settings.AGY_MIN_VERSION}",
                                    code="agy_version_unsupported")

        probe_state = Path(tempfile.mkdtemp(prefix=".preflight-", dir=work_root))
        probe_state.rmdir()
        provision_cli_state(probe_state)

        rc, out, err = await _command(str(path), f"--gemini_dir={probe_state}", "models")
        if rc:
            raise AgyPreflightError("AGY model/auth probe failed", code="agy_not_authenticated")
        models = tuple(line.strip() for line in out.splitlines() if line.strip())
        required = {settings.AGY_MODEL_TRANSLATE, settings.AGY_MODEL_CODEX}
        missing = sorted(required - set(models))
        if missing:
            raise AgyPreflightError(f"Configured AGY model(s) missing: {', '.join(missing)}",
                                    code="agy_model_missing")

        active_plugin = probe_state / "config" / "plugins" / "novelwiki-ai"
        rc, _out, err = await _command(
            str(path), f"--gemini_dir={probe_state}",
            "plugin", "validate", str(active_plugin),
        )
        if rc:
            raise AgyPreflightError(f"NovelWiki AGY plugin validation failed: {err[:300]}",
                                    code="agy_plugin_invalid")
        rc, out, err = await _command(
            str(path), f"--gemini_dir={probe_state}", "plugin", "list",
        )
        if rc:
            raise AgyPreflightError(
                f"AGY active-plugin probe failed: {err[:300]}",
                code="agy_plugin_inactive",
            )
        try:
            imports = json.loads(out).get("imports", [])
        except (AttributeError, json.JSONDecodeError) as exc:
            raise AgyPreflightError(
                "AGY active-plugin probe returned an invalid registry",
                code="agy_plugin_inactive",
            ) from exc
        active = next(
            (item for item in imports if item.get("name") == "novelwiki-ai"), None
        )
        components = set(active.get("components", [])) if active else set()
        if not active or not {"skills", "hooks"}.issubset(components):
            raise AgyPreflightError(
                "NovelWiki AGY plugin is not actively imported with skills and hooks",
                code="agy_plugin_inactive",
            )
        return PreflightResult(True, version, digest, models, settings.AGY_PLUGIN_VERSION,
                               plugin_hash, True)
    except AgyPreflightError as exc:
        if raise_on_error:
            raise
        return PreflightResult(False, version, digest, models, settings.AGY_PLUGIN_VERSION,
                               plugin_hash, False, exc.code, str(exc))
    finally:
        if probe_state is not None:
            shutil.rmtree(probe_state, ignore_errors=True)


if __name__ == "__main__":
    import json

    result = asyncio.run(run_preflight(raise_on_error=False))
    print(json.dumps(result.public(), indent=2))
    raise SystemExit(0 if result.healthy else 1)
