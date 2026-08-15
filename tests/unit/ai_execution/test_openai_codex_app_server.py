from __future__ import annotations

import json

import pytest

from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.client import (
    AppServerSession,
    _classify_codex_request_error,
    _classify_codex_turn_error,
    child_environment,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.contracts import (
    output_schema,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.preflight import (
    validate_binary,
)
from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.runner import (
    materialize_result,
    safe_error_summary,
)
from novelwiki.modules.ai_execution.application.contracts import (
    ENTITY_TYPES,
    RELATIONSHIP_STATE_KEYS,
    STATE_KEYS,
    TERM_TYPES,
    normalize_extraction_candidate,
)
from novelwiki.modules.ai_execution.application.errors import AgyError
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


def test_validate_binary_expands_service_user_home(tmp_path, monkeypatch):
    executable = tmp_path / ".local" / "bin" / "codex"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "novelwiki.modules.ai_execution.adapters.outbound.openai_codex.preflight.settings.OPENAI_CODEX_BINARY",
        "~/.local/bin/codex",
    )
    monkeypatch.setattr(
        "novelwiki.modules.ai_execution.adapters.outbound.openai_codex.preflight.settings.OPENAI_CODEX_BINARY_SHA256",
        "",
    )

    path, digest = validate_binary()

    assert path == executable
    assert len(digest) == 64


@pytest.mark.parametrize(
    "workload",
    [
        "translate_batch",
        "codex_extract",
        "codex_verify",
        "entity_disambiguation",
        "smoke_test",
    ],
)
def test_output_schema_uses_strict_structured_outputs_subset(workload):
    schema = output_schema(workload)

    def assert_strict(value):
        if isinstance(value, list):
            for item in value:
                assert_strict(item)
            return
        if not isinstance(value, dict):
            return
        assert "default" not in value
        properties = value.get("properties")
        if isinstance(properties, dict):
            assert value.get("required") == list(properties)
            assert value.get("additionalProperties") is False
        for item in value.values():
            assert_strict(item)

    assert_strict(schema)


def test_strict_output_schema_keeps_nullable_fields_nullable():
    event = output_schema("codex_extract")["$defs"]["ExtractionEvent"]
    assert "location_ref" in event["required"]
    assert {item.get("type") for item in event["properties"]["location_ref"]["anyOf"]} == {
        "string",
        "null",
    }


def test_strict_output_schema_bounds_unconstrained_json_values():
    state = output_schema("codex_extract")["$defs"]["StateTransitionProposal"]
    value = state["properties"]["value"]
    assert {item.get("type") for item in value["anyOf"]} == {
        "string",
        "number",
        "boolean",
        "null",
        "array",
    }


def test_output_schema_exposes_host_validator_vocabularies():
    extraction_defs = output_schema("codex_extract")["$defs"]
    translation_defs = output_schema("translate_batch")["$defs"]
    assert (
        set(extraction_defs["ExtractionMention"]["properties"]["type"]["enum"])
        == ENTITY_TYPES
    )
    assert set(
        extraction_defs["StateTransitionProposal"]["properties"]["state_key"]["enum"]
    ) == STATE_KEYS
    assert set(
        extraction_defs["RelationshipStateTransitionProposal"]["properties"]["state_key"][
            "enum"
        ]
    ) == RELATIONSHIP_STATE_KEYS
    assert (
        set(translation_defs["TranslationTerm"]["properties"]["term_type"]["enum"])
        == TERM_TYPES
    )


def test_output_schema_requires_nullable_verbatim_evidence_anchors():
    extraction_defs = output_schema("codex_extract")["$defs"]
    for name in (
        "ExtractionFact", "ExtractionRelationship", "ExtractionEvent",
        "ExtractionIdentityReveal", "ExtractionAlias", "StateTransitionProposal",
        "RelationshipStateTransitionProposal", "PlotThreadUpdateProposal",
    ):
        item = extraction_defs[name]
        assert "evidence_text" in item["required"]
        assert {branch.get("type") for branch in item["properties"]["evidence_text"]["anyOf"]} == {
            "string", "null",
        }


def test_materialize_extraction_applies_safe_contract_normalization(tmp_path):
    root = tmp_path / "run"
    (root / "input").mkdir(parents=True)
    (root / "output").mkdir()
    (root / "input" / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-normalize",
                "workload": "codex_extract",
                "chapter_ceiling": 13,
            }
        )
    )
    source_hash = "a" * 64
    (root / "input" / "schema.json").write_text(
        json.dumps({"source_sha256": source_hash, "allowed_chunk_ids": [1]})
    )
    materialize_result(
        root,
        "codex_extract",
        {
            "extraction": {
                "schema_version": "2.2",
                "chapter": 999,
                "source_sha256": "b" * 64,
                "mentions": [],
                "facts": [],
                "relationships": [],
                "events": [],
                "identity_reveals": [],
                "new_aliases": [],
                "state_changes": [],
                "relationship_state_changes": [
                    {
                        "source_ref": "e1",
                        "target_ref": "e2",
                        "state_key": "protective",
                        "operation": "set",
                        "value": "active",
                        "certainty": "confirmed",
                        "source_chunk_ids": [1],
                    }
                ],
                "thread_updates": [],
                "memory_updates": [],
                "warnings": [],
            },
            "running_summary": "A bounded summary.",
            "audit": {"summary": "Checked.", "warnings": []},
        },
    )
    extraction = json.loads((root / "output" / "extraction.json").read_text())
    assert extraction["chapter"] == 13
    assert extraction["source_sha256"] == source_hash
    assert extraction["relationship_state_changes"] == []


def test_grounded_normalizer_drops_nonliteral_mentions_and_dependent_claims():
    candidate, repairs = normalize_extraction_candidate(
        {
            "mentions": [
                {
                    "entity_ref": "m1",
                    "surface_form": "cat-eared maid",
                    "type": "character",
                },
                {"entity_ref": "m2", "surface_form": "Alice", "type": "character"},
            ],
            "facts": [
                {
                    "entity_ref": "m1",
                    "content": "Untrusted normalized mention.",
                    "source_chunk_ids": [11],
                },
                {
                    "entity_ref": "m2",
                    "content": "Grounded mention.",
                    "source_chunk_ids": [11, 99],
                },
            ],
            "events": [
                {"description": "Event.", "participant_refs": ["m1"]},
            ],
            "thread_updates": [
                {"summary": "Update.", "participant_refs": ["m2"]},
            ],
        },
        chapter_text="Alice greeted the cat-eared maids.",
        allowed_chunk_ids={11},
    )

    assert [item["entity_ref"] for item in candidate["mentions"]] == ["m2"]
    assert [item["entity_ref"] for item in candidate["facts"]] == ["m2"]
    assert candidate["facts"][0]["source_chunk_ids"] == [11]
    assert candidate["events"] == []
    assert len(candidate["thread_updates"]) == 1
    assert repairs == (
        "removed 1 nonliteral mention(s)",
        "removed 2 dependent claim(s)",
        "removed 1 unsupplied chunk citation(s)",
    )


@pytest.mark.parametrize(
    ("codex_error_info", "expected_code", "expected_retryable", "expected_detail"),
    [
        ("badRequest", "openai_codex_turn_failed", False, "badRequest"),
        (
            {"httpConnectionFailed": {"httpStatusCode": 503}},
            "openai_codex_provider_unavailable",
            True,
            "httpConnectionFailed (HTTP 503)",
        ),
        (
            "usageLimitExceeded",
            "openai_codex_quota_likely_exhausted",
            True,
            "usageLimitExceeded",
        ),
        ("unauthorized", "openai_codex_not_authenticated", False, "unauthorized"),
    ],
)
def test_codex_error_info_is_safely_classified(
    codex_error_info, expected_code, expected_retryable, expected_detail
):
    code, retryable, detail = _classify_codex_turn_error(
        {
            "codexErrorInfo": codex_error_info,
            "message": "untrusted story text must never be surfaced",
        }
    )
    error = AgyError(
        "OpenAI Codex turn failed",
        code=code,
        retryable=retryable,
        safe_detail=detail,
    )
    summary = safe_error_summary(error)
    assert code == expected_code
    assert retryable is expected_retryable
    assert detail == expected_detail
    assert expected_detail in summary
    assert "untrusted story text" not in summary


@pytest.mark.parametrize(
    ("request_error", "expected_code", "expected_detail"),
    [
        (
            {"code": -32600, "message": "opaque", "data": {"codexErrorInfo": "unauthorized"}},
            "openai_codex_not_authenticated",
            "unauthorized",
        ),
        (
            {"code": 401, "message": "private upstream account message"},
            "openai_codex_not_authenticated",
            "authentication required",
        ),
        (
            {"code": -32600, "message": "Permission denied: private policy name"},
            "openai_codex_permission_blocked",
            "permission blocked",
        ),
    ],
)
def test_request_auth_and_permission_errors_are_safely_classified(
    request_error, expected_code, expected_detail
):
    code, retryable, detail = _classify_codex_request_error(request_error)
    error = AgyError(
        "Codex App Server rejected the request",
        code=code,
        retryable=retryable,
        safe_detail=detail,
    )

    assert code == expected_code
    assert retryable is False
    assert detail == expected_detail
    assert request_error["message"] not in safe_error_summary(error)


@pytest.mark.asyncio
async def test_app_server_request_raises_classified_authentication_error(tmp_path):
    session = AppServerSession(tmp_path)

    async def send(_message):
        return None

    async def read():
        return {
            "id": 1,
            "error": {"code": 401, "message": "expired private session detail"},
        }

    session._send = send
    session._read = read

    with pytest.raises(AgyError) as raised:
        await session.request("thread/start", {})

    assert raised.value.code == "openai_codex_not_authenticated"
    assert raised.value.retryable is False
    assert "expired private session detail" not in safe_error_summary(raised.value)


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
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "novelwiki.modules.ai_execution.adapters.outbound.openai_codex.client.settings.OPENAI_CODEX_BINARY",
        "~/fake-codex",
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
