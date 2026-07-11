from __future__ import annotations

import json
import hashlib
import os
import re
import stat
from pathlib import Path

from pydantic import ValidationError

from novelwiki.modules.ai_execution.adapters.outbound.agy.contracts import OutputManifest
from novelwiki.modules.ai_execution.adapters.outbound.agy.errors import AgyValidationError
from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import sha256_file, workspace_size
from novelwiki.platform.config import settings


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRANSCRIPT_MARKERS = ("system prompt", "developer message", "<tool_call>", "conversationid")
_SECRET_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bAIza[0-9A-Za-z_-]{25,}|"
    r"postgres(?:ql)?://[^\s:/]+:[^\s@]+@",
    re.IGNORECASE,
)


def load_json(path: Path, *, max_bytes: int = 8 * 1024 * 1024, expected_sha256: str | None = None):
    try:
        return json.loads(read_text_artifact(path, max_bytes=max_bytes, expected_sha256=expected_sha256))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise AgyValidationError(f"invalid JSON artifact: {path.name}") from exc


def safe_artifact_path(output_root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise AgyValidationError("unsafe artifact path")
    candidate = output_root / rel
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise AgyValidationError(f"missing artifact: {relative}") from exc
    if output_root.resolve() not in resolved.parents:
        raise AgyValidationError("artifact escapes output root")
    st = candidate.lstat()
    if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_nlink != 1:
        raise AgyValidationError("artifact must be a single-link regular file")
    return candidate


def read_text_artifact(path: Path, *, max_bytes: int = 16 * 1024 * 1024,
                       expected_sha256: str | None = None) -> str:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_nlink != 1:
        raise AgyValidationError("text artifact must be a single-link regular file")
    if st.st_size > max_bytes:
        raise AgyValidationError("text artifact exceeds size cap")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        data = os.read(fd, st.st_size + 1)
        current = os.fstat(fd)
    finally:
        os.close(fd)
    if len(data) != st.st_size or current.st_ino != st.st_ino:
        raise AgyValidationError("artifact changed while being read")
    if expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise AgyValidationError("artifact hash changed before commit", code="agy_hash_mismatch")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgyValidationError("artifact is not valid UTF-8") from exc
    if _CONTROL_RE.search(text):
        raise AgyValidationError("artifact contains forbidden control characters")
    return text


def validate_output_manifest(
    run_root: Path,
    *,
    run_id: str,
    workload: str,
    expected_roles: dict[str, int],
) -> tuple[OutputManifest, dict[str, list[Path]]]:
    try:
        workspace_size(run_root)
    except ValueError as exc:
        raise AgyValidationError(str(exc)) from exc
    output = run_root / "output"
    manifest_path = output / "manifest.json"
    if not manifest_path.exists():
        raise AgyValidationError("output/manifest.json is missing", code="agy_empty_output")
    try:
        manifest = OutputManifest.model_validate(load_json(manifest_path))
    except ValidationError as exc:
        raise AgyValidationError("output manifest schema is invalid", code="agy_manifest_invalid") from exc
    if manifest.run_id != run_id or manifest.workload != workload:
        raise AgyValidationError("output manifest run/workload mismatch", code="agy_manifest_invalid")
    if manifest.status != "complete":
        raise AgyValidationError(manifest.failure_reason or "agent reported failure", code="agy_partial_output")

    by_role: dict[str, list[Path]] = {}
    listed = {"manifest.json"}
    for ref in manifest.artifacts:
        path = safe_artifact_path(output, ref.path)
        if ref.path in listed:
            raise AgyValidationError("duplicate artifact path")
        listed.add(ref.path)
        st = path.stat()
        if st.st_size != ref.bytes or sha256_file(path) != ref.sha256:
            raise AgyValidationError("artifact size/hash mismatch", code="agy_hash_mismatch")
        if ref.media_type.startswith("text/") or ref.media_type in ("application/json", "application/json; charset=utf-8"):
            text = read_text_artifact(path)
            lower = text[:10000].lower()
            if any(marker in lower for marker in _TRANSCRIPT_MARKERS):
                raise AgyValidationError("artifact appears to contain prompt/transcript material")
            if _SECRET_RE.search(text):
                raise AgyValidationError("artifact appears to contain secret material")
        by_role.setdefault(ref.role, []).append(path)

    actual = {role: len(paths) for role, paths in by_role.items()}
    if actual != expected_roles:
        raise AgyValidationError(f"artifact roles mismatch: expected {expected_roles}, got {actual}")
    regular_files = {
        p.relative_to(output).as_posix() for p in output.rglob("*")
        if p.is_file() and not p.is_symlink()
    }
    if regular_files != listed:
        raise AgyValidationError("output contains unlisted or missing files")
    return manifest, by_role
