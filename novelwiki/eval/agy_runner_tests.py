from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from novelwiki.agy.errors import AgyError
from novelwiki.agy.runner import build_argv, child_environment, run_agy
from novelwiki.config.settings import settings


@pytest.fixture()
def fake_runner(tmp_path, monkeypatch):
    fake = Path(__file__).with_name("fake_agy.py")
    monkeypatch.setattr(settings, "AGY_BINARY", str(fake))
    monkeypatch.setattr(settings, "AGY_PRINT_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(settings, "AGY_OUTER_TIMEOUT_GRACE_SECONDS", 0)
    monkeypatch.setattr(settings, "AGY_KILL_GRACE_SECONDS", 1)
    monkeypatch.setattr(settings, "AGY_STDOUT_MAX_BYTES", 4096)
    monkeypatch.setattr(settings, "AGY_STDERR_MAX_BYTES", 4096)
    root = tmp_path / "run"
    (root / "output").mkdir(parents=True)
    (root / "logs").mkdir()
    return root


def test_child_environment_is_positive_allowlist(monkeypatch):
    source = {"HOME": "/tmp/home", "PATH": "/bin", "LANG": "C", "DATABASE_URL": "secret",
              "OPENROUTER_API_KEY": "secret", "GOOGLE_CLIENT_SECRET": "secret", "RANDOM_TOKEN": "secret"}
    env = child_environment(source)
    assert env["HOME"] == "/tmp/home"
    assert env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
    assert not ({"DATABASE_URL", "OPENROUTER_API_KEY", "GOOGLE_CLIENT_SECRET", "RANDOM_TOKEN"} & set(env))


def test_argv_is_vector_and_never_contains_dangerous_flag(fake_runner):
    argv = build_argv(fake_runner, "literal ; $(touch nope)", "Gemini 3.5 Flash (Medium)")
    assert argv[0] == settings.AGY_BINARY
    assert "literal ; $(touch nope)" in argv
    assert "--dangerously-skip-permissions" not in argv


@pytest.mark.asyncio
async def test_runner_closes_stdin_scrubs_env_and_uses_run_cwd(fake_runner, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "must-not-leak")
    result = await run_agy(fake_runner, prompt="inspect:now", model="Gemini 3.5 Flash (Medium)")
    observed = json.loads((fake_runner / "output" / "observed.json").read_text())
    assert result.exit_code == 0 and observed["stdin_closed"] is True
    assert observed["cwd"] == str(fake_runner)
    assert "DATABASE_URL" not in observed["env_keys"]


@pytest.mark.asyncio
async def test_runner_drains_flood_with_bounded_retention(fake_runner):
    result = await run_agy(fake_runner, prompt="flood:now", model="Gemini 3.5 Flash (Medium)")
    assert result.stdout_bytes == 2_000_000 and len(result.stdout_tail.encode()) <= 4096
    assert result.stderr_bytes == 2_000_000 and len(result.stderr_tail.encode()) <= 4096


@pytest.mark.asyncio
async def test_runner_classifies_provider_and_timeout(fake_runner):
    with pytest.raises(AgyError) as provider:
        await run_agy(fake_runner, prompt="nonzero:now", model="Gemini 3.5 Flash (Medium)")
    assert provider.value.code == "agy_provider_unavailable"
    with pytest.raises(AgyError) as timeout:
        await run_agy(fake_runner, prompt="timeout:now", model="Gemini 3.5 Flash (Medium)")
    assert timeout.value.code == "agy_timeout"


@pytest.mark.asyncio
async def test_timeout_terminates_entire_process_group(fake_runner):
    with pytest.raises(AgyError):
        await run_agy(fake_runner, prompt="spawn:now", model="Gemini 3.5 Flash (Medium)")
    child_pid = int((fake_runner / "output" / "child.pid").read_text())
    # A terminated child may briefly remain as a zombie; either state means it can
    # no longer consume subscription work.
    stat_path = Path(f"/proc/{child_pid}/stat")
    if stat_path.exists():
        assert stat_path.read_text().split()[2] == "Z"
