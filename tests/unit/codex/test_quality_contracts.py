from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from novelwiki.modules.ai_execution.public import AgyValidationError, normalize_extraction_candidate
from novelwiki.modules.codex.adapters.outbound.agy import (
    _bounded_task_document,
    _codex_task_document,
    _resumable_codex_workloads,
    validate_extraction_output,
)
from novelwiki.modules.codex.adapters.outbound.context import count_tokens, _reconcile_entity_state
from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
    ClaimAlignmentRecoveryError,
    EvidenceAnchorRecoveryError,
    EXTRACTION_KEYS,
    ThreadRelevanceRecoveryError,
    ThreadUpdateRecoveryError,
    _accept_verified_thread_relevance_issues,
    _evidence_anchor_issues,
    _claim_entity_alignment_issues,
    _duplicate_thread_update_issues,
    _quarantine_alignment_issues,
    _quarantine_duplicate_thread_updates,
    _quarantine_evidence_issues,
    _repair_verified_evidence_issues,
    _thread_relevance_issues,
    _validate_commit_reference_graph,
    _validate_citation_locality,
    _validate_local_reference_graph,
    _validate_memory_updates,
    _validate_summary_text,
)
from novelwiki.modules.codex.adapters.outbound.ingest.link import create_entity
from novelwiki.platform.config import settings


def _empty() -> dict:
    return {key: [] for key in EXTRACTION_KEYS}


def test_resume_never_bypasses_separate_verification():
    assert _resumable_codex_workloads(True) == ("codex_verify",)
    assert _resumable_codex_workloads(False) == ("codex_extract",)


def test_unverified_extraction_cannot_request_verified_evidence_repair():
    with pytest.raises(
        AgyValidationError, match="verified evidence repair requires codex verification"
    ):
        validate_extraction_output(
            Path("."), uuid.uuid4(), 1.0, {}, workload="codex_extract",
            runtime=SimpleNamespace(), evidence_policy="verified",
        )


def test_verifier_task_targets_host_detected_anchor_repairs():
    source = {
        "chunk_ids": {11}, "memory_targets": [], "source_sha256": "a" * 64,
        "roster_map": {"e1": 7}, "thread_map": {}, "marked": "[chunk 11]\nText.",
        "memory_context_json": "{}",
    }
    document = _codex_task_document(
        source, 15.0, draft=_empty(), draft_summary="Summary.",
        grounding_issues=[{
            "group": "facts", "index": 17, "reason": "evidence_not_in_cited_chunks",
        }],
        alignment_issues=[{
            "group": "facts", "index": 2,
            "reason": "fact_missing_referenced_entity_name",
            "missing_refs": ["e1"], "expected_terms": {"e1": ["Rudeus Greyrat"]},
        }],
        thread_issues=[{
            "group": "thread_updates", "index": 1,
            "reason": "duplicate_thread_update", "thread_ref": "t1",
            "first_index": 0,
        }],
        thread_relevance_issues=[{
            "group": "thread_updates", "index": 2,
            "reason": "thread_topic_not_lexically_grounded", "thread_ref": "t9",
            "trusted_title": "Sylphiette's reconnection with Rudeus",
            "trusted_keywords": ["Sylphiette", "Rudeus", "reconnection"],
            "trusted_participants": ["e1", "e14"],
        }],
    )

    assert '"schema_version": "2.2"' in document
    assert '"evidence_text": "short verbatim span from the cited chunk"' in document
    assert "Host-detected evidence repairs required" in document
    assert '"index": 17' in document
    assert "semantically entails" in document
    assert "Never stitch separated lines or omit intervening source words" in document
    assert "Host-detected claim-reference repairs required" in document
    assert "Do not change a ref merely to silence" in document
    assert "Host-detected duplicate thread repairs required" in document
    assert "each thread_ref occurs at most once" in document
    assert "Host-detected semantic thread-topic review required" in document
    assert "Shared participants alone are not sufficient" in document


def test_verifier_uses_separate_headroom_without_dropping_source_or_draft(monkeypatch):
    source = {
        "chunk_ids": {11}, "memory_targets": [], "source_sha256": "a" * 64,
        "roster_map": {"e1": 7}, "thread_map": {},
        "marked": "[chunk 11]\n" + "Long current chapter sentence. " * 100,
        "memory_context_json": '{"entities":[]}',
    }
    draft = _empty()
    draft["facts"] = [{
        "entity_ref": "e1", "fact_type": "action",
        "content": f"Rudeus records supported development {index}.",
        "evidence_text": "Long current chapter sentence",
        "source_chunk_ids": [11],
    } for index in range(20)]
    primary_tokens = count_tokens(_codex_task_document(source, 257.0))
    verifier_document = _codex_task_document(
        source, 257.0, draft=draft, draft_summary="A grounded summary."
    )
    verifier_tokens = count_tokens(verifier_document)
    assert verifier_tokens > primary_tokens
    assert '"facts":[' in verifier_document  # compact but complete draft JSON
    monkeypatch.setattr(settings, "CODEX_CONTEXT_MAX_TOKENS", primary_tokens)
    monkeypatch.setattr(settings, "CODEX_VERIFY_CONTEXT_MAX_TOKENS", verifier_tokens)

    _bounded_task_document(source, 257.0)
    with pytest.raises(AgyValidationError) as exc:
        _bounded_task_document(
            source, 257.0, draft=draft, draft_summary="A grounded summary."
        )
    assert exc.value.code == "codex_context_budget_exceeded"
    assert _bounded_task_document(
        source, 257.0, draft=draft, draft_summary="A grounded summary.",
        max_tokens=settings.CODEX_VERIFY_CONTEXT_MAX_TOKENS,
    ) == verifier_document


def test_generic_entity_mentions_and_dependent_claims_are_removed():
    candidate = _empty()
    candidate["mentions"] = [
        {
            "entity_ref": "m1",
            "surface_form": "courier",
            "type": "character",
            "description": "an unnamed courier",
            "provisional": True,
        },
        {
            "entity_ref": "m2",
            "surface_form": "Rudeus",
            "type": "character",
            "description": "a named mage",
            "provisional": True,
        },
        {
            "entity_ref": "m3",
            "surface_form": "Our house",
            "type": "location",
            "description": "the narrator's unnamed family home",
            "provisional": True,
        },
    ]
    candidate["facts"] = [
        {"entity_ref": "m1", "fact_type": "action", "content": "courier arrived", "source_chunk_ids": [1]},
        {"entity_ref": "m2", "fact_type": "action", "content": "Rudeus arrived", "source_chunk_ids": [1]},
        {"entity_ref": "m3", "fact_type": "setting", "content": "Our house is wooden", "source_chunk_ids": [1]},
    ]

    normalized, repairs = normalize_extraction_candidate(candidate)

    assert [item["entity_ref"] for item in normalized["mentions"]] == ["m2"]
    assert [item["entity_ref"] for item in normalized["facts"]] == ["m2"]
    assert any("generic entity" in repair for repair in repairs)


def _memory_update() -> tuple[dict, list[dict]]:
    chapters = [float(value) for value in range(1, 26)]
    beats = []
    for index in range(0, len(chapters), 5):
        beats.append({
            "chapter_refs": chapters[index:index + 5],
            "summary": (
                "The characters pursue a concrete objective, encounter a durable reversal, "
                "change important relationships, carry forward new knowledge and possessions, "
                "and leave consequences that remain unresolved beyond this chapter group."
            ),
        })
    data = _empty()
    data["memory_updates"] = [{
        "kind": "checkpoint",
        "summary": None,
        "covered_chapters": chapters,
        "key_beats": beats,
        "evidence_chunk_ids": [99],
    }]
    targets = [{"kind": "checkpoint", "covered_chapters": chapters}]
    return data, targets


def test_memory_summary_is_rendered_from_distributed_child_coverage():
    data, targets = _memory_update()

    _validate_memory_updates(data, targets)

    summary = data["memory_updates"][0]["summary"]
    assert summary.startswith("Chapters 1, 2, 3, 4, 5:")
    assert "Chapters 21, 22, 23, 24, 25:" in summary


def test_memory_rejects_endpoint_only_coverage():
    data, targets = _memory_update()
    data["memory_updates"][0]["key_beats"] = [
        data["memory_updates"][0]["key_beats"][-1]
    ]

    with pytest.raises(ValueError, match="partition"):
        _validate_memory_updates(data, targets)


def test_claim_text_must_name_the_entity_it_is_attached_to():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1",
        "fact_type": "advice",
        "content": "Elinalise advises Rudeus to reconsider.",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="name its referenced entity"):
        _validate_local_reference_graph(
            data,
            {"e1": 1, "e2": 2},
            {},
            trusted_entity_terms={"e1": ["Pursena"], "e2": ["Elinalise"]},
        )


def test_same_chapter_alias_is_a_valid_subject_term_for_claims():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "reincarnation",
        "content": "Rudy has been reborn with his prior memories.",
        "source_chunk_ids": [1],
    }]
    data["new_aliases"] = [{
        "entity_ref": "e1", "alias": "Rudy", "is_reveal": True,
        "source_chunk_ids": [1],
    }]

    _validate_local_reference_graph(
        data,
        {"e1": 7},
        {},
        trusted_entity_terms={"e1": ["Pencil Dick"]},
    )


def test_relationship_accepts_unambiguous_first_name_for_new_character():
    data = _empty()
    data["mentions"] = [
        {
            "entity_ref": "m1", "surface_form": "Sauros Boreas Greyrat",
            "type": "character", "description": "Fittoa's liege lord.",
            "provisional": True,
        },
        {
            "entity_ref": "m2", "surface_form": "Philip Boreas Greyrat",
            "type": "character", "description": "Sauros's son.",
            "provisional": True,
        },
    ]
    data["relationships"] = [{
        "source_ref": "m2", "target_ref": "m1", "relation_type": "family",
        "directed": True,
        "content": "Philip Boreas Greyrat calls Sauros his father.",
        "source_chunk_ids": [1],
    }]

    _validate_local_reference_graph(data, {}, {})


def test_fact_accepts_unambiguous_first_name_for_existing_character():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "occupation",
        "content": "Philip was also the town's mayor.",
        "source_chunk_ids": [1],
    }]

    _validate_local_reference_graph(
        data, {"e1": 7}, {},
        trusted_entity_terms={"e1": ["Philip Boreas Greyrat"]},
        trusted_entity_types={"e1": "character"},
    )


def test_fact_does_not_shorten_existing_non_character_name():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "setting",
        "content": "Fittoa is prosperous.", "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="name its referenced entity"):
        _validate_local_reference_graph(
            data, {"e1": 7}, {},
            trusted_entity_terms={"e1": ["Fittoa Region"]},
            trusted_entity_types={"e1": "location"},
        )


def test_relationship_accepts_trusted_inverted_place_name():
    data = _empty()
    data["relationships"] = [{
        "source_ref": "e1", "target_ref": "e2", "relation_type": "honor",
        "directed": True,
        "content": "The Kingdom of Asura praised Perugius for his achievements.",
        "source_chunk_ids": [1],
    }]

    _validate_local_reference_graph(
        data, {"e1": 7, "e2": 8}, {},
        trusted_entity_terms={
            "e1": ["Asura Kingdom"], "e2": ["Perugius Dola"],
        },
        trusted_entity_types={"e1": "location", "e2": "character"},
    )


def test_fact_accepts_trusted_plural_faction_family_form():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "strategy",
        "content": "The Greyrat family used Ghislaine's status as a deterrent.",
        "source_chunk_ids": [1],
    }]

    _validate_local_reference_graph(
        data, {"e1": 7}, {},
        trusted_entity_terms={"e1": ["Greyrats"]},
        trusted_entity_types={"e1": "faction"},
    )


def test_fact_accepts_regular_plural_of_declared_concept_name():
    data = _empty()
    data["mentions"] = [{
        "entity_ref": "m1", "surface_form": "Stone Treant",
        "type": "concept", "description": "A tree-monster.",
        "provisional": False,
    }]
    data["facts"] = [{
        "entity_ref": "m1", "fact_type": "behavior",
        "content": "Stone Treants disguise themselves as rocks.",
        "source_chunk_ids": [1],
    }]

    _validate_local_reference_graph(data, {}, {})


def test_organization_accepts_regular_plural_possessive_name_variant():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "services",
        "content": "The Adventurers’ Guild pays registered adventurers for completed work.",
        "source_chunk_ids": [1],
    }]

    _validate_local_reference_graph(
        data, {"e1": 7}, {},
        trusted_entity_terms={"e1": ["Adventurer's Guild"]},
        trusted_entity_types={"e1": "organization"},
    )


def test_plural_possessive_matching_does_not_accept_dropped_possessive_marker():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "services",
        "content": "The Adventurer Guild pays for completed work.",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="name its referenced entity"):
        _validate_local_reference_graph(
            data, {"e1": 7}, {},
            trusted_entity_terms={"e1": ["Adventurer's Guild"]},
            trusted_entity_types={"e1": "organization"},
        )


def test_regular_plural_matching_does_not_accept_stem_extensions():
    data = _empty()
    data["mentions"] = [{
        "entity_ref": "m1", "surface_form": "Stone Treant",
        "type": "concept", "description": "A tree-monster.",
        "provisional": False,
    }]
    data["facts"] = [{
        "entity_ref": "m1", "fact_type": "behavior",
        "content": "Stone Treantlings disguise themselves as rocks.",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="name its referenced entity"):
        _validate_local_reference_graph(data, {}, {})


def test_character_names_do_not_receive_regular_plural_matching():
    data = _empty()
    data["mentions"] = [{
        "entity_ref": "m1", "surface_form": "Rudeus",
        "type": "character", "description": "A traveling mage.",
        "provisional": False,
    }]
    data["facts"] = [{
        "entity_ref": "m1", "fact_type": "reputation",
        "content": "Several Rudeuses appear in the joke.",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="name its referenced entity"):
        _validate_local_reference_graph(data, {}, {})


def test_isolated_residual_alignment_issue_is_quarantined():
    data = _empty()
    data["facts"] = [
        {
            "entity_ref": "e1", "fact_type": "action",
            "content": "Rudeus leaves the village.", "source_chunk_ids": [1],
        },
        {
            "entity_ref": "e2", "fact_type": "action",
            "content": "Someone follows him.", "source_chunk_ids": [1],
        },
    ]
    terms = {"e1": ["Rudeus"], "e2": ["Eris"]}
    issues = _claim_entity_alignment_issues(data, terms, {})

    recovered, warnings = _quarantine_alignment_issues(data, issues)

    assert [fact["entity_ref"] for fact in recovered["facts"]] == ["e1"]
    assert warnings == (
        "quarantined facts[1] with fact_missing_referenced_entity_name",
    )


def test_broad_residual_alignment_failure_retries_instead_of_hiding_output():
    data = _empty()
    data["facts"] = [
        {
            "entity_ref": f"e{index}", "fact_type": "action",
            "content": "Someone acts.", "source_chunk_ids": [1],
        }
        for index in range(1, 3)
    ]
    terms = {f"e{index}": [f"Person {index}"] for index in range(1, 3)}
    issues = _claim_entity_alignment_issues(data, terms, {})

    with pytest.raises(ClaimAlignmentRecoveryError, match="safe item-level") as exc:
        _quarantine_alignment_issues(data, issues)
    assert exc.value.code == "claim_alignment_broad_failure"


def test_alignment_can_be_deferred_for_independent_verification():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "action",
        "content": "Someone departed.", "source_chunk_ids": [1],
    }]

    issues = _validate_local_reference_graph(
        data, {"e1": 7}, {}, trusted_entity_terms={"e1": ["Rudeus"]},
        trusted_entity_types={"e1": "character"}, alignment_policy="defer",
    )

    assert issues == [{
        "group": "facts", "index": 0,
        "reason": "fact_missing_referenced_entity_name",
        "missing_refs": ["e1"], "expected_terms": {"e1": ["Rudeus"]},
    }]


def test_relationship_rejects_ambiguous_first_name_shorthand():
    data = _empty()
    data["mentions"] = [
        {
            "entity_ref": "m1", "surface_form": "Alex Smith",
            "type": "character", "description": "A guard.", "provisional": True,
        },
        {
            "entity_ref": "m2", "surface_form": "Alex Jones",
            "type": "character", "description": "A merchant.", "provisional": True,
        },
        {
            "entity_ref": "m3", "surface_form": "Rina Vale",
            "type": "character", "description": "A traveler.", "provisional": True,
        },
    ]
    data["relationships"] = [{
        "source_ref": "m3", "target_ref": "m1", "relation_type": "trusts",
        "directed": True, "content": "Rina Vale trusts Alex.",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="name both referenced endpoints"):
        _validate_local_reference_graph(data, {}, {})


def test_relationship_rejects_generic_character_name_prefix():
    data = _empty()
    data["mentions"] = [
        {
            "entity_ref": "m1", "surface_form": "Lord Sauros",
            "type": "character", "description": "A noble.", "provisional": True,
        },
        {
            "entity_ref": "m2", "surface_form": "Philip Boreas Greyrat",
            "type": "character", "description": "A noble.", "provisional": True,
        },
    ]
    data["relationships"] = [{
        "source_ref": "m2", "target_ref": "m1", "relation_type": "family",
        "directed": True, "content": "Philip Boreas Greyrat obeys Lord.",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="name both referenced endpoints"):
        _validate_local_reference_graph(data, {}, {})


def test_internal_candidate_refs_are_rejected_from_reader_text():
    data = _empty()
    data["relationships"] = [{
        "source_ref": "e1",
        "target_ref": "e2",
        "relation_type": "family",
        "directed": False,
        "content": "Rudeus recognizes m1 as family.",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="internal local reference"):
        _validate_local_reference_graph(
            data,
            {"e1": 1, "e2": 2},
            {},
            trusted_entity_terms={"e1": ["Rudeus"], "e2": ["Norn"]},
        )


def test_off_topic_and_unreopened_thread_updates_are_rejected():
    data = _empty()
    data["thread_updates"] = [{
        "thread_ref": "t1",
        "title": None,
        "operation": "advance",
        "summary": "Ariel argues about academy politics.",
        "participant_refs": ["e1"],
        "keywords": ["academy"],
        "certainty": "confirmed",
        "source_chunk_ids": [1],
    }]
    trusted = {
        "t1": {
            "title": "Red Gem Mystery",
            "keywords": ["red gem"],
            "participants": ["e1"],
            "status": "mark_dormant",
        }
    }

    with pytest.raises(ValueError, match="explicitly reopened"):
        _validate_local_reference_graph(
            data, {"e1": 1}, {"t1": 7},
            trusted_threads=trusted,
            chapter_text="Ariel argues at the academy.",
        )
    with pytest.raises(ValueError, match="explicitly reopened"):
        _validate_local_reference_graph(
            data, {"e1": 1}, {"t1": 7},
            trusted_threads=trusted,
            chapter_text="Ariel argues at the academy.",
            thread_relevance_policy="defer",
        )


def test_chapter_135_alias_topic_miss_reaches_independent_verifier():
    data = _empty()
    data["thread_updates"] = [{
        "thread_ref": "t9", "title": None, "operation": "advance",
        "summary": (
            "Fitz decides to reveal Fitz's identity and feelings to Rudeus Greyrat, "
            "though fear of rejection prevents her from acting."
        ),
        "participant_refs": ["e1", "e3", "e14"],
        "keywords": ["reconnection", "identity reveal", "feelings"],
        "certainty": "confirmed",
        "evidence_text": "I had to come out and tell him who I was, and then tell him how I felt.",
        "source_chunk_ids": [13864],
    }]
    trusted = {
        "t9": {
            "title": "Sylphiette's reconnection with Rudeus",
            "keywords": [
                "Sylphiette", "Rudeus", "reconnection", "friendship", "equal",
                "recognition", "sadness",
            ],
            "participants": ["e1", "e14"],
            "status": "advance",
        }
    }
    chapter_text = (
        "Since Rudy started helping Silent, he spent less time on the incident. "
        "Fitz thought: I had to come out and tell him who I was, and then tell him how I felt."
    )

    with pytest.raises(ValueError, match="stable topic"):
        _validate_local_reference_graph(
            data, {"e1": 1, "e3": 3, "e14": 14}, {"t9": 9},
            trusted_threads=trusted, chapter_text=chapter_text,
        )

    _validate_local_reference_graph(
        data, {"e1": 1, "e3": 3, "e14": 14}, {"t9": 9},
        trusted_threads=trusted, chapter_text=chapter_text,
        thread_relevance_policy="defer",
    )
    issues = _thread_relevance_issues(data, trusted, chapter_text)
    assert issues == [{
        "group": "thread_updates", "index": 0,
        "reason": "thread_topic_not_lexically_grounded", "thread_ref": "t9",
        "trusted_title": "Sylphiette's reconnection with Rudeus",
        "trusted_keywords": [
            "Sylphiette", "Rudeus", "reconnection", "friendship", "equal",
            "recognition", "sadness",
        ],
        "trusted_participants": ["e1", "e14"],
    }]
    assert _accept_verified_thread_relevance_issues(data, trusted, issues) == (
        "accepted verifier-reviewed semantic topic grounding for thread_updates[0] t9",
    )


def test_verifier_cannot_override_thread_topic_with_one_shared_character():
    data = _empty()
    data["thread_updates"] = [{
        "thread_ref": "t9", "operation": "advance",
        "summary": "Rudeus eats lunch with an unrelated student.",
        "participant_refs": ["e1", "e3"],
    }]
    trusted = {"t9": {
        "title": "Sylphiette's reconnection with Rudeus",
        "keywords": ["reconnection"], "participants": ["e1", "e14"],
        "status": "advance",
    }}
    issues = _thread_relevance_issues(data, trusted, "Rudy ate lunch with Fitz.")

    with pytest.raises(ThreadRelevanceRecoveryError, match="participant continuity") as exc:
        _accept_verified_thread_relevance_issues(data, trusted, issues)
    assert exc.value.code == "thread_relevance_broad_failure"


def test_atomic_commit_preserves_verified_chapter_135_topic_policy():
    data = _empty()
    data["thread_updates"] = [{
        "thread_ref": "t9", "operation": "advance",
        "summary": "Fitz decides to reveal her identity and feelings to Rudy.",
        "participant_refs": ["e1", "e3", "e14"],
    }]
    manifest = {"thread_terms": {"t9": {
        "title": "Sylphiette's reconnection with Rudeus",
        "keywords": ["Sylphiette", "Rudeus", "reconnection"],
        "participants": ["e1", "e14"], "status": "advance",
    }}}
    chapter_text = "Fitz had to tell Rudy who she was and how she felt."

    with pytest.raises(ValueError, match="stable topic"):
        _validate_commit_reference_graph(
            data, {"e1": 1, "e3": 3, "e14": 14}, {"t9": 9},
            manifest, chapter_text,
        )

    _validate_commit_reference_graph(
        data, {"e1": 1, "e3": 3, "e14": 14}, {"t9": 9},
        manifest, chapter_text, thread_relevance_verified=True,
    )


def test_multiple_verifier_retained_thread_topic_misses_retry():
    data = _empty()
    data["thread_updates"] = [
        {"thread_ref": ref, "operation": "advance", "summary": "Unrelated scene.",
         "participant_refs": participants}
        for ref, participants in (
            ("t1", ["e1", "e2"]), ("t2", ["e3", "e4"])
        )
    ]
    trusted = {
        "t1": {"title": "First mystery", "keywords": ["first mystery"],
               "participants": ["e1", "e2"], "status": "advance"},
        "t2": {"title": "Second mystery", "keywords": ["second mystery"],
               "participants": ["e3", "e4"], "status": "advance"},
    }
    issues = _thread_relevance_issues(data, trusted, "An unrelated scene happens.")

    with pytest.raises(ThreadRelevanceRecoveryError, match="safe verifier-reviewed threshold") as exc:
        _accept_verified_thread_relevance_issues(data, trusted, issues)
    assert exc.value.code == "thread_relevance_broad_failure"


def test_duplicate_existing_thread_updates_are_deferred_to_verifier():
    data = _empty()
    data["thread_updates"] = [
        {
            "thread_ref": "t1", "title": None, "operation": "advance",
            "summary": summary, "participant_refs": [], "keywords": ["search"],
            "certainty": "confirmed", "source_chunk_ids": [1],
        }
        for summary in (
            "Paul organizes the Search and Rescue Squad.",
            "Geese expands the search through the Great Forest.",
        )
    ]

    with pytest.raises(ValueError, match="at most one update"):
        _validate_local_reference_graph(data, {}, {"t1": 7})

    _validate_local_reference_graph(
        data, {}, {"t1": 7}, thread_duplicate_policy="defer"
    )
    assert _duplicate_thread_update_issues(data) == [{
        "group": "thread_updates", "index": 1,
        "reason": "duplicate_thread_update", "thread_ref": "t1",
        "first_index": 0,
    }]


def test_new_thread_open_and_duplicate_advance_can_reach_verifier():
    data = _empty()
    data["thread_updates"] = [
        {
            "thread_ref": "p1", "title": "Missing Family Search",
            "operation": "open", "summary": "Paul begins a family search.",
            "participant_refs": [], "keywords": ["family", "search"],
            "certainty": "confirmed", "source_chunk_ids": [1],
        },
        {
            "thread_ref": "p1", "title": None, "operation": "advance",
            "summary": "Geese recruits more searchers.", "participant_refs": [],
            "keywords": ["searchers"], "certainty": "confirmed",
            "source_chunk_ids": [1],
        },
    ]

    _validate_local_reference_graph(
        data, {}, {}, thread_duplicate_policy="defer"
    )


def test_one_unresolved_duplicate_thread_update_is_quarantined():
    data = _empty()
    data["thread_updates"] = [
        {"thread_ref": "t1", "summary": "first"},
        {"thread_ref": "t1", "summary": "second"},
        {"thread_ref": "t3", "summary": "other"},
    ]

    recovered, warnings = _quarantine_duplicate_thread_updates(
        data, _duplicate_thread_update_issues(data)
    )

    assert [item["summary"] for item in recovered["thread_updates"]] == [
        "first", "other",
    ]
    assert warnings == ("quarantined thread_updates[1] duplicate for t1",)


def test_broad_duplicate_thread_output_retries_instead_of_hiding_loss():
    data = _empty()
    data["thread_updates"] = [
        {"thread_ref": "t1", "summary": "first"},
        {"thread_ref": "t1", "summary": "second"},
        {"thread_ref": "t2", "summary": "third"},
        {"thread_ref": "t2", "summary": "fourth"},
    ]

    with pytest.raises(ThreadUpdateRecoveryError, match="recovery threshold") as exc:
        _quarantine_duplicate_thread_updates(
            data, _duplicate_thread_update_issues(data)
        )
    assert exc.value.code == "thread_update_broad_failure"


def test_stale_transient_state_and_living_state_after_death_are_removed(monkeypatch):
    state = {
        "life_status": {"value": "dead", "chapter": 50.0},
        "goal": {"value": "rescue Zenith", "chapter": 10.0},
        "occupation": {"value": "adventurer", "chapter": 40.0},
        "condition": {"value": "wounded", "chapter": 90.0},
        "last_known_location": {"value": "Buena Village", "chapter": 1.0},
    }

    _reconcile_entity_state(state, 250.0)

    assert set(state) == {"life_status"}


def test_transient_state_recorded_at_chapter_zero_can_expire():
    state = {"condition": {"value": "wounded", "chapter": 0.0}}

    _reconcile_entity_state(state, 31.0)

    assert state == {}


@pytest.mark.asyncio
async def test_new_entity_does_not_duplicate_its_canonical_name_as_an_alias():
    class Connection:
        def __init__(self):
            self.execute_calls = []

        async def fetchval(self, query, *args):
            assert "INSERT INTO entities" in query
            return 42

        async def execute(self, query, *args):
            self.execute_calls.append((query, args))

    class AI:
        async def get_embedding(self, text):
            return []

    conn = Connection()
    entity_id = await create_entity(
        7, "Klein Moretti", "character", 1.0, conn,
        runtime=SimpleNamespace(ai=AI()),
    )

    assert entity_id == 42
    assert conn.execute_calls == []


def test_evidence_anchor_must_be_local_to_cited_chunk():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1",
        "fact_type": "action",
        "content": "Rudeus rescues Zenith from the labyrinth.",
        "evidence_text": "pulled Zenith free",
        "source_chunk_ids": [2],
    }]

    with pytest.raises(ValueError, match="evidence_not_in_cited_chunks"):
        _validate_citation_locality(data, {2: "Cliff studies a magical implement."})


def test_semantically_supported_paraphrase_uses_verbatim_evidence_anchor():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1",
        "fact_type": "relationship",
        "content": "Rudeus thanks Zenith for giving birth to him.",
        "evidence_text": "thank you for having me",
        "source_chunk_ids": [2],
    }]

    _validate_citation_locality(
        data,
        {2: 'Rudy scratched his head. "Well… thank you for having me."'},
    )


def test_claim_word_overlap_is_not_mistaken_for_grounding():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "action",
        "content": "Rudeus rescues Zenith from the labyrinth.",
        "evidence_text": "Rudeus studies the labyrinth map",
        "source_chunk_ids": [2],
    }]

    # The host proves that the anchor is local. Semantic entailment belongs to
    # the independent verifier, which must drop this unsupported claim.
    _validate_citation_locality(
        data, {2: "Rudeus studies the labyrinth map with Cliff."},
    )


def test_evidence_anchor_normalizes_case_punctuation_and_whitespace_only():
    data = _empty()
    data["relationships"] = [{
        "source_ref": "e1", "target_ref": "m1",
        "relation_type": "family", "directed": True,
        "content": "Paul is Rudeus's father.",
        "evidence_text": '"PAUL   welcomed Rudeus"',
        "source_chunk_ids": [2],
    }]

    _validate_citation_locality(
        data,
        {2: "Paul welcomed Rudeus into the house."},
    )


def test_evidence_anchor_ignores_dialogue_delimiters_but_not_changed_words():
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "employment",
        "content": "Rudeus earns two silver pieces per month.",
        "evidence_text": (
            "Do you know how much I earn every month for teaching you?\n\n"
            '"About five gold pieces?"\n\n"Two silver pieces," I said.'
        ),
        "source_chunk_ids": [2],
    }]

    _validate_citation_locality(data, {2: (
        '"Do you know how much I earn every month for teaching you?"\n\n'
        '“About five gold pieces?”\n\n“Two silver pieces,” I said.'
    )})

    data["facts"][0]["evidence_text"] = data["facts"][0]["evidence_text"].replace(
        "Two silver", "Three silver"
    )
    with pytest.raises(ValueError, match="evidence_not_in_cited_chunks"):
        _validate_citation_locality(data, {2: (
            '"Do you know how much I earn every month for teaching you?"\n\n'
            '"About five gold pieces?"\n\n"Two silver pieces," I said.'
        )})


def test_evidence_anchor_normalizes_apostrophe_typography():
    data = _empty()
    data["events"] = [{
        "description": "Ghislaine identifies Perugius's fortress.",
        "significance": None, "participant_refs": ["e1"],
        "event_type": "discovery",
        "evidence_text": "That's Perugius's floating fortress, Ghislaine explained.",
        "source_chunk_ids": [2],
    }]

    _validate_citation_locality(
        data,
        {2: '“Is it your first time seeing it? That’s Perugius’s floating fortress,” '
            "Ghislaine explained."},
    )


def test_verified_anchor_repair_restores_omitted_words_and_overlap_citation():
    data = _empty()
    proposal = (
        '"So please—marry me."\n\nCome to think of it, this might be the first time '
        'I\'d explicitly asked.\n\n"…Yes." Her cheeks heated up as she nodded.'
    )
    reassurance = (
        'Sylphie considered it for a moment, then lowered her eyes. With a sad look on her '
        'face, she smiled and said, "Just don\'t suddenly disappear on me, okay?"\n\n'
        '"Yeah." I understand. I won\'t suddenly disappear.'
    )
    stitched = '"So please—marry me."\n\n"…Yes." Her cheeks heated up as she nodded.'
    data["events"] = [{
        "description": "Rudeus proposes and Sylphiette accepts.",
        "participant_refs": ["e1", "e2"], "location_ref": None,
        "significance": "They become engaged.", "evidence_text": stitched,
        "source_chunk_ids": [10],
    }]
    data["thread_updates"] = [{
        "thread_ref": "t1", "title": None, "operation": "advance",
        "summary": "Rudeus promises not to disappear.",
        "participant_refs": ["e1", "e2"], "keywords": ["promise"],
        "certainty": "confirmed", "evidence_text": reassurance,
        "source_chunk_ids": [10],
    }]
    chunks = {
        10: proposal,
        11: reassurance,
    }
    issues = _evidence_anchor_issues(data, chunks)
    assert len(issues) == 2

    repaired, warnings = _repair_verified_evidence_issues(data, chunks, issues)

    assert _evidence_anchor_issues(repaired, chunks) == []
    assert "Come to think of it" in repaired["events"][0]["evidence_text"]
    assert repaired["events"][0]["source_chunk_ids"] == [10]
    assert repaired["thread_updates"][0]["source_chunk_ids"] == [11]
    assert any("restored" in warning for warning in warnings)
    assert any("relocated" in warning for warning in warnings)


@pytest.mark.parametrize(
    ("source", "invalid"),
    [
        ("He gave her two silver coins.", "He gave her three silver coins."),
        ("Rudeus thanked Sylphie warmly.", "Sylphie thanked Rudeus warmly."),
        (
            "Rudeus proposed. " + "unrelated " * 30 + "Sylphie accepted.",
            "Rudeus proposed. Sylphie accepted.",
        ),
    ],
)
def test_verified_anchor_repair_rejects_changed_reordered_or_distant_text(source, invalid):
    data = _empty()
    data["facts"] = [{
        "entity_ref": "e1", "fact_type": "action", "content": "A claim.",
        "evidence_text": invalid, "source_chunk_ids": [2],
    }]
    issues = _evidence_anchor_issues(data, {2: source})

    repaired, warnings = _repair_verified_evidence_issues(data, {2: source}, issues)

    assert _evidence_anchor_issues(repaired, {2: source}) == issues
    assert warnings == ()


def test_one_bad_claim_is_quarantined_without_losing_valid_claims():
    data = _empty()
    data["facts"] = [
        {
            "entity_ref": "e1", "fact_type": "action", "content": f"Fact {index}",
            "evidence_text": evidence, "source_chunk_ids": [2],
        }
        for index, evidence in enumerate(("valid one", "not present", "valid two", "valid three"))
    ]
    issues = _evidence_anchor_issues(
        data, {2: "Valid one appears before valid two and valid three."},
    )

    recovered, warnings = _quarantine_evidence_issues(data, issues)

    assert [item["content"] for item in recovered["facts"]] == ["Fact 0", "Fact 2", "Fact 3"]
    assert warnings == ("quarantined facts[1] has evidence_not_in_cited_chunks",)


def test_broad_grounding_failure_retries_the_chapter_instead_of_hiding_loss():
    data = _empty()
    data["facts"] = [
        {
            "entity_ref": "e1", "fact_type": "action", "content": f"Fact {index}",
            "evidence_text": "absent", "source_chunk_ids": [2],
        }
        for index in range(2)
    ]
    issues = _evidence_anchor_issues(data, {2: "Unrelated passage."})

    with pytest.raises(EvidenceAnchorRecoveryError, match="recovery threshold") as exc:
        _quarantine_evidence_issues(data, issues)
    assert exc.value.code == "evidence_anchor_broad_failure"


def test_quarantined_identity_reveal_removes_dependent_identity_state():
    data = _empty()
    data["identity_reveals"] = [{
        "persona_ref": "e1", "true_entity_ref": "e2", "note": "A reveal.",
        "evidence_text": "absent", "source_chunk_ids": [2],
    }]
    data["state_changes"] = [{
        "entity_ref": "e1", "state_key": "identity", "operation": "set",
        "value": None, "value_entity_ref": "e2", "perspective_ref": None,
        "certainty": "confirmed", "narrative_scope": "current",
        "evidence_text": "the masks were one", "source_chunk_ids": [2],
    }]
    issues = _evidence_anchor_issues(data, {2: "The masks were one."})

    recovered, warnings = _quarantine_evidence_issues(data, issues)

    assert recovered["identity_reveals"] == []
    assert recovered["state_changes"] == []
    assert warnings[-1] == "quarantined 1 dependent identity state change(s)"


def test_cross_entity_identity_state_requires_explicit_identity_reveal():
    data = _empty()
    data["mentions"] = [{
        "entity_ref": "m1", "surface_form": "Rudy", "type": "character",
        "description": "A newly spoken name.", "provisional": False,
    }]
    data["state_changes"] = [{
        "entity_ref": "m1", "state_key": "identity", "operation": "set",
        "value": None, "value_entity_ref": "e1", "perspective_ref": None,
        "certainty": "confirmed", "narrative_scope": "current",
        "source_chunk_ids": [1],
    }]

    with pytest.raises(ValueError, match="explicit identity reveal"):
        _validate_local_reference_graph(data, {"e1": 7}, {})

    data["identity_reveals"] = [{
        "persona_ref": "m1", "true_entity_ref": "e1",
        "note": "Rudy retains Pencil Dick's prior memories.",
        "source_chunk_ids": [1],
    }]
    with pytest.raises(ValueError, match="must be an alias"):
        _validate_local_reference_graph(data, {"e1": 7}, {})

    data["mentions"] = []
    data["state_changes"][0]["entity_ref"] = "e2"
    data["identity_reveals"][0]["persona_ref"] = "e2"
    _validate_local_reference_graph(data, {"e1": 7, "e2": 8}, {})


def test_summary_rejects_internal_chunk_notation():
    source = " ".join(["story"] * 800)
    summary = " ".join(["Grounded development"] * 55) + " [chunk 7]"

    with pytest.raises(ValueError, match="internal"):
        _validate_summary_text(summary, source)


def test_summary_accepts_focused_long_chapter_digest():
    source = " ".join(["story"] * 1600)
    summary = " ".join(["Grounded development"] * 33)

    assert _validate_summary_text(summary, source) == summary
