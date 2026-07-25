import json
from types import SimpleNamespace

import pytest

from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
    EXTRACTION_KEYS,
    _call_and_parse,
    _coerce_extraction,
)


def _groups(**overrides):
    groups = {key: [] for key in EXTRACTION_KEYS}
    groups.update(overrides)
    return groups


def test_coerce_extraction_applies_only_safe_contract_normalization():
    original = _groups(
        mentions=[
            {
                "entity_ref": "e1",
                "surface_form": "Rudeus",
                "type": "character",
            },
            {
                "entity_ref": "m1",
                "surface_form": "Sylph",
                "type": "character",
            },
        ],
        state_changes=[
            {
                "entity_ref": "e1",
                "state_key": "age",
                "operation": "set",
                "value": 10,
                "source_chunk_ids": [101],
            },
            {
                "entity_ref": "e1",
                "state_key": "condition",
                "operation": "set",
                "value": "injured",
                "source_chunk_ids": [101],
            },
        ],
        relationship_state_changes=[
            {
                "source_ref": "e1",
                "target_ref": "m1",
                "state_key": "affection",
                "operation": "set",
                "value": "growing",
                "source_chunk_ids": [101],
            },
            {
                "source_ref": "e1",
                "target_ref": "m1",
                "state_key": "trust",
                "operation": "set",
                "value": "established",
                "source_chunk_ids": [101],
            },
        ],
    )

    normalized = _coerce_extraction(original)

    assert [item["entity_ref"] for item in normalized["mentions"]] == ["m1"]
    assert [item["state_key"] for item in normalized["state_changes"]] == ["condition"]
    assert [
        item["state_key"] for item in normalized["relationship_state_changes"]
    ] == ["trust"]
    assert len(original["mentions"]) == 2
    assert len(original["state_changes"]) == 2


def test_coerce_extraction_keeps_reference_and_provenance_failures_strict():
    invalid = _groups(
        facts=[
            {
                "entity_ref": "e1",
                "fact_type": "action",
                "content": "Acted without cited evidence.",
                "source_chunk_ids": [],
            }
        ]
    )

    with pytest.raises(ValueError):
        _coerce_extraction(invalid)


@pytest.mark.asyncio
async def test_call_and_parse_gives_any_provider_compact_validation_feedback():
    invalid = _groups(
        mentions=[
            {
                "entity_ref": "x1",
                "surface_form": "Rudeus",
                "type": "character",
            }
        ]
    )
    responses = [json.dumps(invalid), json.dumps(_groups())]

    class FakeAi:
        def __init__(self):
            self.calls = []

        async def call_chat_completion(self, **kwargs):
            self.calls.append(kwargs)
            return responses.pop(0)

    ai = FakeAi()
    result = await _call_and_parse(
        [{"role": "system", "content": "extract"}],
        "Chapter 13 extraction",
        SimpleNamespace(ai=ai),
    )

    assert result == _groups()
    assert len(ai.calls) == 2
    retry = ai.calls[1]["messages"]
    assert retry[:-1] == ai.calls[0]["messages"]
    assert retry[-1]["role"] == "user"
    assert "Trusted validation rejected" in retry[-1]["content"]
    assert "`mentions[].entity_ref`" in retry[-1]["content"]
    assert "mentions.[].entity_ref" in retry[-1]["content"]
    assert "deepseek" not in retry[-1]["content"].lower()
