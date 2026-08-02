from __future__ import annotations

import json

import pytest

from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.client import (
    AppServerSession,
    child_environment,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.contracts import (
    output_schema,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.runner import (
    materialize_result,
)
from novelwiki.platform.config.settings import _replace_database_host


def test_child_environment_drops_application_secrets(tmp_path):
    root = tmp_path / "run"
    env = child_environment(
        root,
        {
            "HOME": "/safe/home",
            "PATH": "/bin",
            "DATABASE_URL": "postgres://secret",
            "OPENAI_API_KEY": "secret",
            "SESSION_SECRET": "secret",
        },
    )
    assert env["HOME"] == "/safe/home"
    assert env["CODEX_HOME"].endswith(".run.codex-home")
    assert "DATABASE_URL" not in env
    assert "OPENAI_API_KEY" not in env
    assert "SESSION_SECRET" not in env


def test_host_worker_database_override_preserves_credentials_and_database():
    value = "postgresql://user:p%40ss@host.docker.internal:5432/novelwiki?sslmode=disable"
    assert _replace_database_host(value, "127.0.0.1") == (
        "postgresql://user:p%40ss@127.0.0.1:5432/novelwiki?sslmode=disable"
    )


def test_materialize_translation_uses_trusted_source_metadata(tmp_path):
    root = tmp_path / "run"
    (root / "input" / "chapters").mkdir(parents=True)
    (root / "output").mkdir()
    (root / "input" / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "workload": "translate_batch"})
    )
    source_hash = "a" * 64
    (root / "input" / "chapters" / "c000001.meta.json").write_text(
        json.dumps(
            {
                "chapter_ref": "c000001",
                "source_sha256": source_hash,
                "source_content_version": 7,
            }
        )
    )
    materialize_result(
        root,
        "translate_batch",
        {
            "chapters": [
                {
                    "chapter_ref": "c000001",
                    "translated_title": "Arrival",
                    "translation": "The traveler arrived.",
                    "new_terms": [],
                    "self_review": {
                        "complete": True,
                        "paragraphs_preserved": True,
                        "glossary_checked": True,
                    },
                }
            ]
        },
    )
    metadata = json.loads(
        (root / "output" / "chapters" / "c000001.meta.json").read_text()
    )
    manifest = json.loads((root / "output" / "manifest.json").read_text())
    assert metadata["source_sha256"] == source_hash
    assert metadata["source_content_version"] == 7
    assert {item["role"] for item in manifest["artifacts"]} == {
        "translation",
        "translation_meta",
    }


@pytest.mark.asyncio
async def test_app_server_jsonl_turn_is_structured_and_collects_usage(
    tmp_path, monkeypatch
):
    executable = tmp_path / "fake-codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if 'id' not in message:
        continue
    ident, method = message['id'], message['method']
    if method == 'initialize':
        print(json.dumps({'id': ident, 'result': {}}), flush=True)
    elif method == 'thread/start':
        print(json.dumps({'id': ident, 'result': {'thread': {'id': 'thread-1'}}}), flush=True)
    elif method == 'turn/start':
        print(json.dumps({'id': ident, 'result': {'turn': {'id': 'turn-1'}}}), flush=True)
        print(json.dumps({'method': 'thread/tokenUsage/updated', 'params': {
            'threadId': 'thread-1', 'turnId': 'turn-1',
            'tokenUsage': {'last': {'inputTokens': 4, 'cachedInputTokens': 1,
                'outputTokens': 2, 'reasoningOutputTokens': 1, 'totalTokens': 6},
                'total': {'inputTokens': 4, 'cachedInputTokens': 1,
                'outputTokens': 2, 'reasoningOutputTokens': 1, 'totalTokens': 6}}
        }}), flush=True)
        print(json.dumps({'method': 'item/completed', 'params': {
            'item': {'id': 'item-1', 'type': 'agentMessage', 'text': '{\"ready\":\"READY\"}'}}
        }), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {
            'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'completed'}}
        }), flush=True)
"""
    )
    executable.chmod(0o700)
    run_root = tmp_path / "workspace"
    run_root.mkdir()
    monkeypatch.setattr(
        "novelwiki.modules.ai_execution.adapters.outbound.openai_codex.client.settings.OPENAI_CODEX_BINARY",
        str(executable),
    )
    session = AppServerSession(run_root)
    try:
        await session.start()
        await session.initialize()
        result = await session.run_turn(
            model="test-model",
            effort="medium",
            developer_instructions="Return the schema.",
            user_input="smoke",
            output_schema=output_schema("smoke_test"),
        )
    finally:
        await session.close()
    assert result.value == {"ready": "READY"}
    assert result.metrics()["openai_codex_total_tokens"] == 6
    assert result.thread_id == "thread-1"
    assert result.turn_id == "turn-1"
