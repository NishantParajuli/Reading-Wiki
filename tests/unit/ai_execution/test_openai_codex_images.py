from __future__ import annotations
import base64
import io
from unittest.mock import AsyncMock
import pytest
from PIL import Image
from novelwiki.modules.ai_execution.application.errors import AgyError, AgyCanceled
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.images import (
    ImageSession,
    image_bytes,
)


def png():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(out, format="PNG")
    return out.getvalue()


def test_native_result_is_validated_without_trusting_file_paths(tmp_path):
    data = png()
    assert image_bytes({"result": base64.b64encode(data).decode()}, tmp_path) == data
    with pytest.raises(AgyError):
        image_bytes(
            {"result": base64.b64encode(b"\x89PNG\r\n\x1a\ncorrupt").decode()}, tmp_path
        )
    with pytest.raises(AgyError):
        image_bytes({"savedPath": "/etc/passwd"}, tmp_path)
    with pytest.raises(AgyError, match="usage limit"):
        image_bytes({"failure": {"type": "usageLimitExceeded"}}, tmp_path)


@pytest.mark.asyncio
async def test_image_turn_attaches_references_uses_luna_max_and_stops_after_first_image(
    tmp_path,
):
    data = png()
    ref = tmp_path / "reference.png"
    ref.write_bytes(data)
    session = ImageSession(tmp_path)
    session.request = AsyncMock(
        side_effect=[{"thread": {"id": "thread1"}}, {"turn": {"id": "turn1"}}]
    )
    session._read = AsyncMock(
        return_value={
            "method": "item/completed",
            "params": {
                "item": {
                    "id": "image1",
                    "type": "imageGeneration",
                    "status": "completed",
                    "result": base64.b64encode(data).decode(),
                }
            },
        }
    )
    assert await session.generate("An original scene", [ref]) == data
    thread = session.request.call_args_list[0].args[1]
    turn = session.request.call_args_list[1].args[1]
    assert thread["config"]["features.shell_tool"] is False
    assert turn["model"] == "gpt-6-luna" and turn["effort"] == "max"
    assert turn["input"][1] == {"type": "localImage", "path": str(ref)}
    assert session._read.await_count == 1


@pytest.mark.asyncio
async def test_image_cancellation_and_unexpected_client_tool_fail_closed(tmp_path):
    session = ImageSession(tmp_path)
    session.request = AsyncMock(
        side_effect=[{"thread": {"id": "t"}}, {"turn": {"id": "u"}}]
    )
    with pytest.raises(AgyCanceled):
        await session.generate("scene", [], cancel_check=AsyncMock(return_value=True))
    session.request = AsyncMock(
        side_effect=[{"thread": {"id": "t"}}, {"turn": {"id": "u"}}]
    )
    session._read = AsyncMock(
        return_value={"id": 7, "method": "item/tool/call", "params": {}}
    )
    with pytest.raises(AgyError, match="interactive"):
        await session.generate("scene", [])


@pytest.mark.asyncio
async def test_illustration_model_requirement_precedes_workspace_or_provider_work():
    from types import SimpleNamespace
    from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.illustration_runner import (
        IllustrationRenderer,
    )

    renderer = IllustrationRenderer(
        {}, SimpleNamespace(models=("gpt-5.6-terra",)), None
    )
    with pytest.raises(AgyError, match="require gpt-6-luna"):
        await renderer.image("scene", [])


@pytest.mark.asyncio
async def test_renderer_checks_max_support_and_cleans_up_before_any_image_turn(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from novelwiki.modules.ai_execution.adapters.outbound.openai_codex import (
        illustration_runner as runner,
    )

    root = tmp_path / "run"
    root.mkdir()
    (root / "input").mkdir()
    session = SimpleNamespace(
        start=AsyncMock(),
        initialize=AsyncMock(),
        close=AsyncMock(),
        process=SimpleNamespace(pid=123),
        request=AsyncMock(
            return_value={
                "data": [
                    {
                        "model": "gpt-6-luna",
                        "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(runner, "ImageSession", lambda root: session)
    monkeypatch.setattr(runner, "create_run", AsyncMock(return_value="run-id"))
    monkeypatch.setattr(runner, "update_run", AsyncMock())
    monkeypatch.setattr(runner, "create_run_workspace", lambda *args: root)
    monkeypatch.setattr(runner, "workspace_relpath", lambda root: "run")
    monkeypatch.setattr(runner, "_proc_start_time", lambda pid: "123")
    renderer = runner.IllustrationRenderer(
        {"id": 1}, SimpleNamespace(models=["gpt-6-luna"], version="0.157.1"), None
    )
    operation = AsyncMock()
    with pytest.raises(AgyError, match="MAX reasoning"):
        await renderer._run(operation, images=True)
    operation.assert_not_called()
    session.close.assert_awaited_once()
    assert not root.exists()


def test_empty_or_failed_image_uses_provider_wait_instead_of_publishing(tmp_path):
    for item in (
        {"status": "failed", "result": ""},
        {"status": "completed", "result": ""},
    ):
        with pytest.raises(AgyError) as error:
            image_bytes(item, tmp_path)
        assert error.value.code == "openai_codex_provider_unavailable"
