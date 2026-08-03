from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from novelwiki.modules.ai_execution.adapters.outbound.openai_codex import smoke
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.client import (
    AppServerResult,
)
from novelwiki.modules.ai_execution.application.errors import AgyCanceled, AgyError


class Work:
    async def is_canceled(self, _job_id):
        return False


def prepare_smoke(monkeypatch, tmp_path):
    run_id = uuid4()
    root = tmp_path / "run"
    (root / "input").mkdir(parents=True)
    (root / "output").mkdir()
    updates = []

    async def create_run(**_kwargs):
        return run_id

    async def update_run(_run_id, **fields):
        updates.append(fields)

    monkeypatch.setattr(smoke, "create_run", create_run)
    monkeypatch.setattr(smoke, "update_run", update_run)
    monkeypatch.setattr(smoke, "create_run_workspace", lambda *_args: root)
    monkeypatch.setattr(smoke, "seal_inputs", lambda _root: None)
    monkeypatch.setattr(smoke, "workspace_relpath", lambda _root: "1/run")
    return root, updates


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (AgyError("failed", code="openai_codex_turn_failed"), "failed"),
        (AgyCanceled("canceled", code="openai_codex_canceled"), "canceled"),
    ],
)
async def test_smoke_turn_failure_is_persisted_as_terminal(
    monkeypatch, tmp_path, error, expected_status
):
    _, updates = prepare_smoke(monkeypatch, tmp_path)

    async def fail_run(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(smoke, "run_openai_codex", fail_run)

    with pytest.raises(type(error)):
        await smoke.run_smoke_test(
            {"id": 8, "attempts": 1},
            SimpleNamespace(version="0.146.0", plugin_sha256="a" * 64),
            Work(),
        )

    terminal = updates[-1]
    assert terminal["status"] == expected_status
    assert terminal["failure_code"] == error.code
    assert terminal["finished_at"] is not None


@pytest.mark.asyncio
async def test_smoke_validation_failure_keeps_process_metrics(monkeypatch, tmp_path):
    _, updates = prepare_smoke(monkeypatch, tmp_path)
    result = AppServerResult(value={"ready": "READY"}, exit_code=7, stdout_bytes=42)

    async def run(*_args, **_kwargs):
        return result

    monkeypatch.setattr(smoke, "run_openai_codex", run)
    monkeypatch.setattr(
        smoke,
        "validate_output_manifest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("invalid")),
    )

    with pytest.raises(RuntimeError, match="invalid"):
        await smoke.run_smoke_test(
            {"id": 8, "attempts": 1},
            SimpleNamespace(version="0.146.0", plugin_sha256="a" * 64),
            Work(),
        )

    terminal = updates[-1]
    assert terminal["status"] == "failed"
    assert terminal["exit_code"] == 7
    assert terminal["metrics"]["stdout_bytes"] == 42
    assert terminal["finished_at"] is not None
