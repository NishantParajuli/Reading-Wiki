from __future__ import annotations
import base64
import io
import struct
import zlib
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


def test_relative_image_artifact_resolves_inside_run_workspace(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "image.png").write_bytes(png())
    assert image_bytes({"savedPath": "output/image.png"}, tmp_path) == png()
    with pytest.raises(AgyError) as error:
        image_bytes({"savedPath": "../outside.png"}, tmp_path)
    assert error.value.code == "openai_codex_artifact_invalid"


def test_oversized_saved_image_is_invalid_instead_of_empty_provider_result(tmp_path, monkeypatch):
    from novelwiki.modules.ai_execution.adapters.outbound.openai_codex import images

    monkeypatch.setattr(images, "MAX_IMAGE_BYTES", 32)
    path = tmp_path / "image.png"
    path.write_bytes(png())
    with pytest.raises(AgyError) as error:
        image_bytes({"savedPath": str(path)}, tmp_path)
    assert error.value.code == "openai_codex_artifact_invalid"


def test_png_with_valid_checksums_but_invalid_compressed_pixels_is_rejected(tmp_path):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", b"invalid zlib pixels")
        + chunk(b"IEND", b"")
    )
    with Image.open(io.BytesIO(data)) as image:
        image.verify()  # This alone used to accept the corrupt artifact.
    with pytest.raises(AgyError, match="corrupt"):
        image_bytes({"result": base64.b64encode(data).decode()}, tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("early", [True, False])
async def test_image_notifications_before_start_reply_are_not_lost(tmp_path, early):
    session = ImageSession(tmp_path)
    session._send = AsyncMock()
    image_event = {
        "method": "item/completed", "params": {"item": {
            "id": "image", "type": "imageGeneration", "status": "completed",
            "result": base64.b64encode(png()).decode(),
        }},
    }
    reply = {"id": 2, "result": {"turn": {"id": "turn"}}}
    session._read = AsyncMock(side_effect=[
        {"id": 1, "result": {"thread": {"id": "thread"}}},
        *([image_event, reply] if early else [reply, image_event]),
    ])
    assert await session.generate("Scene", []) == png()
    assert session._read.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("early", [True, False])
@pytest.mark.parametrize("status,info,code", [
    ("completed", None, "openai_codex_provider_unavailable"),
    ("failed", "usageLimitExceeded", "openai_codex_quota_likely_exhausted"),
    ("failed", "unauthorized", "openai_codex_not_authenticated"),
])
async def test_terminal_image_turn_is_classified_even_before_start_reply(tmp_path, early, status, info, code):
    session = ImageSession(tmp_path)
    session._send = AsyncMock()
    event = {"method": "turn/completed", "params": {"turn": {
        "id": "turn", "status": status, "error": {"codexErrorInfo": info},
    }}}
    reply = {"id": 2, "result": {"turn": {"id": "turn"}}}
    session._read = AsyncMock(side_effect=[
        {"id": 1, "result": {"thread": {"id": "thread"}}},
        *([event, reply] if early else [reply, event]),
    ])
    with pytest.raises(AgyError) as error:
        await session.generate("Scene", [])
    assert error.value.code == code
    assert session._read.await_count == 3


@pytest.mark.asyncio
async def test_image_thread_without_id_has_protocol_error(tmp_path):
    session = ImageSession(tmp_path)
    session.request = AsyncMock(return_value={"thread": {}})
    with pytest.raises(AgyError) as error:
        await session.generate("Scene", [])
    assert error.value.code == "openai_codex_protocol_error"
    session.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_illustration_planner_sends_strict_schema_for_optional_name_history(
    tmp_path,
):
    from types import SimpleNamespace
    from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.illustration_runner import (
        IllustrationRenderer,
    )
    from novelwiki.modules.codex.domain.illustrations import IllustrationPlan

    session = SimpleNamespace(
        run_turn=AsyncMock(return_value=SimpleNamespace(value={"name_updates": []}))
    )
    renderer = IllustrationRenderer({}, None, None)

    async def run(operation):
        return await operation(session, tmp_path, AsyncMock())

    renderer._run = run
    schema = IllustrationPlan.model_json_schema()
    assert "name_updates" not in schema["required"]  # Old saved plans still load.
    await renderer.plan("instructions", {}, schema)
    transmitted = session.run_turn.call_args.kwargs["output_schema"]
    assert set(transmitted["required"]) == set(transmitted["properties"])
    assert transmitted["additionalProperties"] is False
    assert session.run_turn.call_args.kwargs["effort"] == "max"
