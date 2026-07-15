from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from novelwiki.agy.errors import AgyValidationError
from novelwiki.agy.validators import validate_output_manifest
from novelwiki.agy.workspace import create_run_workspace, seal_inputs, tree_sha256
from novelwiki.agy import PLUGIN_SOURCE
from novelwiki.config.settings import settings


def _write_contract(root: Path, *, run_id="run-1", artifact_path="result.txt", content=b"ok\n"):
    output = root / "output"; output.mkdir(parents=True)
    artifact = output / artifact_path; artifact.parent.mkdir(parents=True, exist_ok=True); artifact.write_bytes(content)
    manifest = {"schema_version": "1.0", "run_id": run_id, "workload": "test",
                "status": "complete", "artifacts": [{"path": artifact_path,
                "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
                "media_type": "text/plain; charset=utf-8", "role": "result"}],
                "warnings": [], "completed_at": datetime.now(UTC).isoformat()}
    (output / "manifest.json").write_text(json.dumps(manifest))


def test_valid_hashed_contract(tmp_path):
    _write_contract(tmp_path)
    manifest, roles = validate_output_manifest(tmp_path, run_id="run-1", workload="test",
                                                expected_roles={"result": 1})
    assert manifest.status == "complete" and roles["result"][0].read_text() == "ok\n"


@pytest.mark.parametrize("mutation", ["wrong_hash", "extra_file", "traversal", "control"])
def test_invalid_contracts_are_rejected(tmp_path, mutation):
    _write_contract(tmp_path)
    manifest_path = tmp_path / "output" / "manifest.json"
    data = json.loads(manifest_path.read_text())
    if mutation == "wrong_hash": data["artifacts"][0]["sha256"] = "0" * 64
    elif mutation == "extra_file": (tmp_path / "output" / "extra.txt").write_text("extra")
    elif mutation == "traversal": data["artifacts"][0]["path"] = "../result.txt"
    elif mutation == "control":
        content = b"bad\x00text"; (tmp_path / "output" / "result.txt").write_bytes(content)
        data["artifacts"][0].update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(AgyValidationError):
        validate_output_manifest(tmp_path, run_id="run-1", workload="test", expected_roles={"result": 1})


def test_symlink_and_hardlink_are_rejected(tmp_path):
    _write_contract(tmp_path)
    result = tmp_path / "output" / "result.txt"
    target = tmp_path / "target.txt"; target.write_text("ok\n")
    result.unlink(); result.symlink_to(target)
    with pytest.raises(AgyValidationError):
        validate_output_manifest(tmp_path, run_id="run-1", workload="test", expected_roles={"result": 1})
    result.unlink(); os.link(target, result)
    with pytest.raises(AgyValidationError):
        validate_output_manifest(tmp_path, run_id="run-1", workload="test", expected_roles={"result": 1})


def test_workspace_copies_exact_pinned_plugin_and_seals_inputs(tmp_path, monkeypatch):
    work = tmp_path / "private-agy"
    credentials = tmp_path / "credentials"
    credentials.mkdir()
    token = credentials / "antigravity-oauth-token"
    token.write_text("fake-test-token")
    token.chmod(0o600)
    monkeypatch.setattr(settings, "AGY_WORK_DIR", str(work))
    monkeypatch.setattr(settings, "AGY_CREDENTIAL_DIR", str(credentials))
    monkeypatch.setattr(settings, "AGY_PLUGIN_SHA256", tree_sha256(PLUGIN_SOURCE))
    root = create_run_workspace(12, "run-safe")
    (root / "input" / "manifest.json").write_text("{}")
    seal_inputs(root)
    copied = root / ".agents" / "vendor" / "novelwiki-ai"
    assert tree_sha256(copied) == settings.AGY_PLUGIN_SHA256
    assert not list(copied.rglob("*.pyc"))
    assert (root / "input" / "manifest.json").stat().st_mode & 0o777 == 0o400
    assert (root / "output").stat().st_mode & 0o777 == 0o700
    assert (root / ".agents" / "hooks.json").is_file()
    assert not (root / ".agents" / "skills").exists()
    assert (root / ".git" / "HEAD").read_text() == "ref: refs/heads/novelwiki-run\n"
    assert (root / ".git").stat().st_mode & 0o777 == 0o500
    hooks = json.loads((root / ".agents" / "hooks.json").read_text())
    assert hooks["novelwiki-tool-gate"]["PreToolUse"][0]["hooks"][0]["command"] == (
        "python3 vendor/novelwiki-ai/hooks/tool_gate.py"
    )
    state = root.parent / ".run-safe.agy-state"
    assert not (state / "config" / "plugins").exists()
    assert (state / "antigravity-cli" / "antigravity-oauth-token").is_symlink()
    cli_settings_path = state / "antigravity-cli" / "settings.json"
    assert cli_settings_path.is_file() and not cli_settings_path.is_symlink()
    cli_settings = json.loads(cli_settings_path.read_text())
    assert cli_settings == {
        "agentMode": settings.AGY_MODE or "accept-edits",
        "artifactReviewPolicy": settings.AGY_ARTIFACT_REVIEW_POLICY,
        "model": settings.AGY_MODEL_TRANSLATE,
        "toolPermission": settings.AGY_TOOL_PERMISSION,
        "trustedWorkspaces": [str(root.resolve())],
    }
    assert state not in root.parents and root not in state.parents


def test_plugin_stop_hook_requires_the_complete_output_manifest_contract(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "input" / "manifest.json").write_text(json.dumps({
        "run_id": "run-hook", "workload": "smoke_test",
    }))
    artifact = b"READY\n"
    (tmp_path / "output" / "smoke.txt").write_bytes(artifact)
    incomplete = {
        "status": "complete",
        "artifacts": [{
            "path": "smoke.txt", "sha256": hashlib.sha256(artifact).hexdigest(),
            "bytes": len(artifact), "media_type": "text/plain; charset=utf-8", "role": "smoke",
        }],
    }
    manifest_path = tmp_path / "output" / "manifest.json"
    manifest_path.write_text(json.dumps(incomplete))
    hook = runpy.run_path(str(PLUGIN_SOURCE / "hooks" / "validate_stop.py"))["validate"]
    assert "missing or extra" in hook(str(tmp_path))

    complete = {
        "schema_version": "1.0", "run_id": "run-hook", "workload": "smoke_test",
        "status": "complete", "artifacts": incomplete["artifacts"], "warnings": [],
        "completed_at": datetime.now(UTC).isoformat(), "failure_reason": None,
    }
    manifest_path.write_text(json.dumps(complete))
    assert hook(str(tmp_path)) is None


def test_plugin_stop_hook_finalizes_hashes_without_a_terminal(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    (tmp_path / "input" / "manifest.json").write_text(json.dumps({
        "run_id": "run-finalize", "workload": "smoke_test",
    }))
    (tmp_path / "output" / "smoke.txt").write_text("READY\n")
    module = runpy.run_path(str(PLUGIN_SOURCE / "hooks" / "validate_stop.py"))
    assert module["finalize_manifest"](str(tmp_path)) is True
    assert module["validate"](str(tmp_path)) is None
    manifest = json.loads((tmp_path / "output" / "manifest.json").read_text())
    assert manifest["artifacts"][0]["sha256"] == hashlib.sha256(b"READY\n").hexdigest()


def test_plugin_tool_gate_denies_terminal_and_outside_workspace(tmp_path):
    hook = PLUGIN_SOURCE / "hooks" / "tool_gate.py"

    def invoke(name, args):
        result = subprocess.run(
            [sys.executable, str(hook)],
            input=json.dumps({
                "toolCall": {"name": name, "args": args},
                "workspacePaths": [str(tmp_path)],
            }),
            text=True, capture_output=True, check=True, cwd=tmp_path,
        )
        return json.loads(result.stdout)

    assert invoke("Bash", {"command": "true"})["decision"] == "deny"
    assert invoke("ListDirectory", {"DirectoryPath": "."})["decision"] == "deny"
    assert invoke("ReadFile", {"AbsolutePath": "/etc/passwd"})["decision"] == "deny"
    assert invoke("Edit", {"TargetFile": "output/result.txt"})["decision"] == "allow"


def test_plugin_stop_hook_enforces_codex_source_snapshot_identity(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "output").mkdir()
    expected_source_hash = "a" * 64
    transport_file_hash = "b" * 64
    (tmp_path / "input" / "manifest.json").write_text(json.dumps({
        "run_id": "run-codex", "workload": "codex_extract", "chapter_ceiling": 2.0,
    }))
    (tmp_path / "input" / "schema.json").write_text(json.dumps({
        "source_sha256": expected_source_hash,
    }))
    extraction_path = tmp_path / "output" / "extraction.json"
    manifest_path = tmp_path / "output" / "manifest.json"

    def write_output(chapter, source_hash):
        content = json.dumps({"chapter": chapter, "source_sha256": source_hash}).encode()
        extraction_path.write_bytes(content)
        manifest_path.write_text(json.dumps({
            "schema_version": "1.0", "run_id": "run-codex", "workload": "codex_extract",
            "status": "complete", "artifacts": [{
                "path": "extraction.json", "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content), "media_type": "application/json",
                "role": "codex_extraction",
            }], "warnings": [], "completed_at": datetime.now(UTC).isoformat(),
            "failure_reason": None,
        }))

    hook = runpy.run_path(str(PLUGIN_SOURCE / "hooks" / "validate_stop.py"))["validate"]
    write_output(3.0, transport_file_hash)
    assert "chapter_ceiling" in hook(str(tmp_path))
    write_output(2.0, transport_file_hash)
    error = hook(str(tmp_path))
    assert "input/schema.json source_sha256" in error
    assert "chapter.md artifact hash" in error
    write_output(2.0, expected_source_hash)
    assert hook(str(tmp_path)) is None


def test_plugin_stop_hook_enforces_exact_translation_metadata(tmp_path):
    (tmp_path / "input" / "chapters").mkdir(parents=True)
    (tmp_path / "output" / "chapters").mkdir(parents=True)
    source_hash = "a" * 64
    input_meta = {
        "chapter_ref": "c000001", "source_sha256": source_hash,
        "source_content_version": 2,
    }
    input_meta_path = tmp_path / "input" / "chapters" / "c000001.meta.json"
    input_meta_path.write_text(json.dumps(input_meta))
    (tmp_path / "input" / "manifest.json").write_text(json.dumps({
        "run_id": "run-translation", "workload": "translate_batch",
        "inputs": [{"role": "chapter_metadata", "path": "chapters/c000001.meta.json"}],
    }))
    translation = b"Translated text.\n"
    translation_path = tmp_path / "output" / "chapters" / "c000001.translation.txt"
    translation_path.write_bytes(translation)
    meta_path = tmp_path / "output" / "chapters" / "c000001.meta.json"

    def write_output(metadata):
        content = json.dumps(metadata).encode()
        meta_path.write_bytes(content)
        artifacts = [
            {
                "path": "chapters/c000001.translation.txt",
                "sha256": hashlib.sha256(translation).hexdigest(), "bytes": len(translation),
                "media_type": "text/plain; charset=utf-8", "role": "translation",
            },
            {
                "path": "chapters/c000001.meta.json",
                "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
                "media_type": "application/json", "role": "translation_meta",
            },
        ]
        (tmp_path / "output" / "manifest.json").write_text(json.dumps({
            "schema_version": "1.0", "run_id": "run-translation",
            "workload": "translate_batch", "status": "complete", "artifacts": artifacts,
            "warnings": [], "completed_at": datetime.now(UTC).isoformat(),
            "failure_reason": None,
        }))

    valid = {
        "schema_version": "1.0", "chapter_ref": "c000001",
        "source_sha256": source_hash, "source_content_version": 2,
        "translated_title": "Chapter 1", "translation_path": "c000001.translation.txt",
        "new_terms": [], "self_review": {
            "complete": True, "paragraphs_preserved": True, "glossary_checked": True,
        },
    }
    hook = runpy.run_path(str(PLUGIN_SOURCE / "hooks" / "validate_stop.py"))["validate"]
    write_output({**valid, "number": 1.0})
    assert "missing or extra" in hook(str(tmp_path))
    write_output(valid)
    assert hook(str(tmp_path)) is None
