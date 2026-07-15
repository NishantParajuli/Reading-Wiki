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
    monkeypatch.setattr(settings, "AGY_MAX_MODEL_REQUESTS_PER_RUN", 16)
    monkeypatch.setattr(settings, "AGY_MAX_EMPTY_PLANNER_RESPONSES", 2)
    monkeypatch.setattr(settings, "AGY_REQUIRED_LOADED_HOOKS", 2)
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
    assert any(value.startswith("--gemini_dir=") for value in argv)
    assert "--dangerously-skip-permissions" not in argv


@pytest.mark.asyncio
async def test_runner_closes_stdin_scrubs_env_and_uses_run_cwd(fake_runner, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "must-not-leak")
    result = await run_agy(fake_runner, prompt="inspect:now", model="Gemini 3.5 Flash (Medium)")
    observed = json.loads((fake_runner / "output" / "observed.json").read_text())
    assert result.exit_code == 0 and observed["stdin_closed"] is True
    assert observed["cwd"] == str(fake_runner)
    assert "DATABASE_URL" not in observed["env_keys"]
    assert result.model_requests == 1 and result.hooks_loaded == 2


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


@pytest.mark.asyncio
async def test_runner_fails_closed_when_plugin_hooks_are_not_loaded(fake_runner):
    with pytest.raises(AgyError) as failure:
        await run_agy(
            fake_runner, prompt="hooks0:now", model="Gemini 3.5 Flash (Medium)"
        )
    assert failure.value.code == "agy_plugin_inactive"
    assert failure.value.metrics["agy_hooks_loaded"] == 0


@pytest.mark.asyncio
async def test_runner_fails_closed_on_unexpected_extra_hooks(fake_runner):
    with pytest.raises(AgyError) as failure:
        await run_agy(
            fake_runner, prompt="hooks3:now", model="Gemini 3.5 Flash (Medium)"
        )
    assert failure.value.code == "agy_plugin_inactive"
    assert failure.value.metrics["agy_hooks_loaded"] == 3


@pytest.mark.asyncio
async def test_runner_stops_runaway_model_request_fanout(fake_runner):
    with pytest.raises(AgyError) as failure:
        await run_agy(
            fake_runner, prompt="request_limit:now", model="Gemini 3.5 Flash (Medium)"
        )
    assert failure.value.code == "agy_request_limit"
    assert failure.value.metrics["agy_model_requests"] > 16


@pytest.mark.asyncio
async def test_runner_fails_closed_when_loaded_hook_command_breaks(fake_runner):
    with pytest.raises(AgyError) as failure:
        await run_agy(
            fake_runner, prompt="hook_failure:now", model="Gemini 3.5 Flash (Medium)"
        )
    assert failure.value.code == "agy_hook_failure"
    assert failure.value.metrics["agy_hook_failures"] == 1


@pytest.mark.asyncio
async def test_runner_stops_empty_planner_response_loop(fake_runner):
    with pytest.raises(AgyError) as failure:
        await run_agy(
            fake_runner, prompt="planner_loop:now", model="Gemini 3.5 Flash (Medium)"
        )
    assert failure.value.code == "agy_planner_loop"
    assert failure.value.metrics["agy_empty_planner_responses"] > 2


@pytest.mark.asyncio
async def test_runner_allows_planner_tool_steps_when_output_progresses(fake_runner, monkeypatch):
    monkeypatch.setattr(settings, "AGY_PRINT_TIMEOUT_SECONDS", 8)
    result = await run_agy(
        fake_runner, prompt="planner_progress:now", model="Gemini 3.5 Flash (Medium)"
    )
    assert result.exit_code == 0
    assert result.empty_planner_responses == 6
    assert (fake_runner / "output" / "progress.txt").read_text() == "2"
