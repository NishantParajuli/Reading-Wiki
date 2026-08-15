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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("evidence_text", "reason"),
    [
        (None, "missing_evidence_text"),
        ("Rudeus departed from Tingen", "evidence_not_in_cited_chunks"),
    ],
)
async def test_direct_api_extraction_rejects_missing_or_invented_evidence(
    monkeypatch, evidence_text, reason,
):
    from novelwiki.modules.codex.adapters.outbound.ingest import extract

    proposal = _groups(facts=[{
        "entity_ref": "e1",
        "fact_type": "action",
        "content": "Rudeus arrived in Tingen.",
        "evidence_text": evidence_text,
        "source_chunk_ids": [7],
    }])

    class Connection:
        async def fetchval(self, *_args, **_kwargs):
            return False

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    async def get_pool():
        return Pool()

    async def load_chunks(*_args):
        return "[chunk 7]\nRudeus arrived in Tingen.", {7}, [7]

    async def build_context(*_args, **_kwargs):
        return {
            "token_count": 1,
            "roster_map": {"e1": 1},
            "thread_map": {},
            "roster_terms": {"e1": ["Rudeus"]},
            "roster_types": {"e1": "character"},
            "thread_terms": {},
            "memory_targets": [],
            "serialized": "{}",
            "context_sha256": "context-hash",
            "manifest": {"dropped_entities": []},
        }

    async def no_op(*_args, **_kwargs):
        return None

    class Reading:
        async def chapter_snapshot(self, *_args):
            return {"title": "Arrival", "content": "Rudeus arrived in Tingen."}

    class AI:
        def __init__(self):
            self.calls = 0

        async def call_chat_completion(self, **_kwargs):
            self.calls += 1
            return json.dumps(proposal)

    ai = AI()
    runtime = SimpleNamespace(ai=ai, reading=Reading())
    monkeypatch.setattr(extract, "get_db_pool", get_pool)
    monkeypatch.setattr(extract, "_load_chapter_chunks", load_chunks)
    monkeypatch.setattr(extract, "build_chapter_context", build_context)
    monkeypatch.setattr(extract, "clear_caches", no_op)
    monkeypatch.setattr(extract.settings, "EXTRACTION_VERIFY", False)

    with pytest.raises(ValueError, match=reason):
        await extract.extract_knowledge_for_chapter(1, 1.0, runtime=runtime)

    assert ai.calls == 1
