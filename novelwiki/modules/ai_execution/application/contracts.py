"""Stable DTOs exchanged with AI Execution clients."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactRef(StrictModel):
    path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=80)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
            raise ValueError("artifact paths must be relative and cannot traverse")
        return value.replace("\\", "/")


class InputManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    job_id: int
    workload: str
    plugin_version: str
    model: str
    novel_ref: str
    chapter_ceiling: float | None = None
    inputs: list[ArtifactRef]
    output_dir: Literal["../output"] = "../output"
    limits: dict = Field(default_factory=dict)
    created_at: datetime


class OutputManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    workload: str
    status: Literal["complete", "failed"]
    artifacts: list[ArtifactRef]
    warnings: list[str] = Field(default_factory=list, max_length=100)
    completed_at: datetime
    failure_reason: str | None = Field(default=None, max_length=500)


TERM_TYPES = {"name", "place", "skill", "item", "term", "faction", "organization", "concept"}


class TranslationTerm(StrictModel):
    source_term: str = Field(min_length=1, max_length=200)
    translation: str = Field(min_length=1, max_length=200)
    term_type: str = Field(
        default="term",
        min_length=1,
        max_length=40,
        json_schema_extra={"enum": sorted(TERM_TYPES)},
    )

    @field_validator("term_type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in TERM_TYPES:
            raise ValueError("unknown term type")
        return value


class TranslationSelfReview(StrictModel):
    complete: bool
    paragraphs_preserved: bool
    glossary_checked: bool


class TranslationMeta(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    chapter_ref: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_content_version: int = Field(ge=1)
    translated_title: str = Field(min_length=1, max_length=500)
    translation_path: str
    new_terms: list[TranslationTerm] = Field(default_factory=list, max_length=2000)
    self_review: TranslationSelfReview


ENTITY_TYPES = {"character", "location", "faction", "item", "concept", "organization"}
STATE_KEYS = {
    "last_known_location", "life_status", "occupation", "rank", "affiliation",
    "possession", "ability", "identity", "title", "goal", "knowledge",
    "condition", "custody",
}
RELATIONSHIP_STATE_KEYS = {
    "status", "affiliation", "family", "romantic", "trust", "hostility", "hierarchy",
}
EntityRef = Annotated[str, Field(pattern=r"^(?:e|m)[1-9][0-9]*$", max_length=80)]
MentionRef = Annotated[str, Field(pattern=r"^m[1-9][0-9]*$", max_length=80)]
ThreadRef = Annotated[str, Field(pattern=r"^(?:t|p)[1-9][0-9]*$", max_length=80)]
Keyword = Annotated[str, Field(min_length=1, max_length=100)]
WarningText = Annotated[str, Field(max_length=500)]
_ROSTER_REF_RE = re.compile(r"^e[1-9][0-9]*$")
_EXTRACTION_REF_FIELDS = (
    "entity_ref",
    "source_ref",
    "target_ref",
    "persona_ref",
    "true_entity_ref",
    "location_ref",
    "value_entity_ref",
    "perspective_ref",
)
_EXTRACTION_CLAIM_GROUPS = (
    "facts",
    "relationships",
    "events",
    "identity_reveals",
    "new_aliases",
    "state_changes",
    "relationship_state_changes",
    "thread_updates",
)
_GENERIC_ENTITY_SURFACES = {
    "courier", "giant lizard", "hydra", "lucky rat", "dining hall", "pub",
    "yellow cylinder", "man", "young man", "old man", "woman", "young woman",
    "young lady", "boy", "girl", "child", "baby", "maid", "maidservant",
    "young mistress", "master", "teacher", "professor", "guard", "soldier",
    "merchant", "innkeeper", "adventurer", "doctor", "nurse", "driver",
    "the protagonist", "the narrator", "mother", "father", "sister", "brother",
}
_PERSON_ROLE_WORDS = {
    "man", "woman", "boy", "girl", "child", "baby", "lady", "maid", "mistress",
    "master", "guard", "soldier", "merchant", "teacher", "professor", "doctor",
    "nurse", "driver",
}
_DESCRIPTIVE_PERSON_MODIFIERS = {
    "young", "old", "elderly", "middle-aged", "little", "big", "large", "tall",
    "short", "thin", "slender", "stocky", "burly", "muscular", "fat", "pale",
    "beautiful", "handsome", "pretty", "masked", "hooded", "cloaked", "armored",
    "scarred", "bearded", "bald", "blind", "wounded", "injured", "dying", "dead",
    "mysterious", "strange", "unknown", "unnamed",
}


def _is_descriptive_person_surface(value: str) -> bool:
    """Identify short descriptor-only role phrases without rejecting proper names."""
    tokens = re.findall(r"[A-Za-z][A-Za-z'’.-]*", value)
    if not 2 <= len(tokens) <= 3 or tokens[-1].casefold() not in _PERSON_ROLE_WORDS:
        return False
    modifiers = [token.casefold().strip(".'’-") for token in tokens[:-1]]
    possessive_description = modifiers[0].endswith(("'s", "’s"))
    return possessive_description or all(
        modifier in _DESCRIPTIVE_PERSON_MODIFIERS for modifier in modifiers
    )


def eligible_entity_surface(surface: str, entity_type: str) -> bool:
    """Conservative host-side named-entity gate shared by every AI backend."""
    value = " ".join((surface or "").strip().split())
    if not value or len(value) > 160 or value.casefold() in _GENERIC_ENTITY_SURFACES:
        return False
    # Determiner- and pronoun-led descriptions are contextual noun phrases, not
    # stable names. Treating "our house" or "his mother" as lore entities causes
    # long-book rosters to grow with one-off duplicates.
    if value.casefold().startswith((
        "a ", "an ", "the ", "my ", "our ", "your ", "his ", "her ",
        "its ", "their ", "this ", "that ", "these ", "those ",
    )):
        return False
    # CJK proper names have no case distinction. For Latin-script output, require
    # at least one uppercase letter so ordinary lowercase nouns cannot become lore.
    has_cased_letter = any(char.isalpha() and (char.islower() or char.isupper()) for char in value)
    if has_cased_letter and not any(char.isupper() for char in value):
        return False
    if entity_type == "character" and _is_descriptive_person_surface(value):
        return False
    return True


def _literal_surface_occurs(surface: str, chapter_text: str) -> bool:
    surface = surface.strip()
    if not surface:
        return False
    return re.search(
        rf"(?<!\w){re.escape(surface)}(?!\w)", chapter_text, re.IGNORECASE
    ) is not None


def _extraction_item_refs(item: dict[str, Any]) -> set[str]:
    refs = {
        str(item[field])
        for field in _EXTRACTION_REF_FIELDS
        if item.get(field)
    }
    refs.update(str(ref) for ref in (item.get("participant_refs") or []) if ref)
    return refs


def normalize_extraction_candidate(
    value: Any,
    *,
    chapter_text: str | None = None,
    allowed_chunk_ids: set[int] | None = None,
) -> tuple[Any, tuple[str, ...]]:
    """Apply narrow, loss-minimizing repairs before strict extraction validation.

    Existing roster refs are valid in claims but redundant in ``mentions``, whose
    records only declare new local ``mN`` refs. Temporal state keys are closed
    vocabularies; an item outside those vocabularies cannot be committed safely, so
    discard that optional item without weakening validation for the rest of the
    payload. When trusted chapter text is supplied, remove nonliteral new mentions
    and only the claims that depend on those local refs. When trusted chunk ids are
    supplied, mixed provenance keeps its valid ids and removes only unsupplied ids;
    provenance with no valid id remains untouched so strict validation rejects it.
    All other malformed shapes and references remain strict validation errors.
    """
    if not isinstance(value, dict):
        return value, ()

    candidate = deepcopy(value)
    repairs: list[str] = []

    mentions = candidate.get("mentions")
    if isinstance(mentions, list):
        kept_mentions = [
            item for item in mentions
            if not (
                isinstance(item, dict)
                and isinstance(item.get("entity_ref"), str)
                and _ROSTER_REF_RE.fullmatch(item["entity_ref"])
            )
        ]
        removed = len(mentions) - len(kept_mentions)
        if removed:
            candidate["mentions"] = kept_mentions
            repairs.append(f"removed {removed} redundant roster mention(s)")

    for group, allowed, label in (
        ("state_changes", STATE_KEYS, "entity-state transition(s)"),
        (
            "relationship_state_changes",
            RELATIONSHIP_STATE_KEYS,
            "relationship-state transition(s)",
        ),
    ):
        items = candidate.get(group)
        if not isinstance(items, list):
            continue
        kept_items = [
            item for item in items
            if not (
                isinstance(item, dict)
                and isinstance(item.get("state_key"), str)
                and item["state_key"] not in allowed
            )
        ]
        removed = len(items) - len(kept_items)
        if removed:
            candidate[group] = kept_items
            repairs.append(f"removed {removed} unsupported {label}")

    if chapter_text is not None:
        mentions = candidate.get("mentions")
        invalid_refs: set[str] = set()
        if isinstance(mentions, list):
            kept_mentions = []
            for item in mentions:
                invalid = (
                    isinstance(item, dict)
                    and isinstance(item.get("entity_ref"), str)
                    and isinstance(item.get("surface_form"), str)
                    and not _literal_surface_occurs(item["surface_form"], chapter_text)
                )
                if invalid:
                    invalid_refs.add(item["entity_ref"])
                else:
                    kept_mentions.append(item)
            removed = len(mentions) - len(kept_mentions)
            if removed:
                candidate["mentions"] = kept_mentions
                repairs.append(f"removed {removed} nonliteral mention(s)")

        if invalid_refs:
            removed_claims = 0
            for group in _EXTRACTION_CLAIM_GROUPS:
                items = candidate.get(group)
                if not isinstance(items, list):
                    continue
                kept_items = [
                    item
                    for item in items
                    if not (
                        isinstance(item, dict)
                        and _extraction_item_refs(item) & invalid_refs
                    )
                ]
                removed_claims += len(items) - len(kept_items)
                candidate[group] = kept_items
            if removed_claims:
                repairs.append(f"removed {removed_claims} dependent claim(s)")

    mentions = candidate.get("mentions")
    if isinstance(mentions, list):
        invalid_refs = {
            str(item.get("entity_ref"))
            for item in mentions
            if isinstance(item, dict)
            and isinstance(item.get("entity_ref"), str)
            and isinstance(item.get("surface_form"), str)
            and isinstance(item.get("type"), str)
            and not eligible_entity_surface(item["surface_form"], item["type"])
        }
        if invalid_refs:
            candidate["mentions"] = [
                item for item in mentions
                if not isinstance(item, dict) or item.get("entity_ref") not in invalid_refs
            ]
            removed_claims = 0
            for group in _EXTRACTION_CLAIM_GROUPS:
                items = candidate.get(group)
                if not isinstance(items, list):
                    continue
                kept_items = [
                    item for item in items
                    if not (
                        isinstance(item, dict)
                        and _extraction_item_refs(item) & invalid_refs
                    )
                ]
                removed_claims += len(items) - len(kept_items)
                candidate[group] = kept_items
            repairs.append(f"removed {len(invalid_refs)} generic entity mention(s)")
            if removed_claims:
                repairs.append(
                    f"removed {removed_claims} generic-entity dependent claim(s)"
                )

    if allowed_chunk_ids is not None:
        removed_citations = 0

        def repair_ids(item: Any, field: str) -> None:
            nonlocal removed_citations
            if not isinstance(item, dict) or not isinstance(item.get(field), list):
                return
            submitted = item[field]
            repaired: list[int] = []
            for raw_id in submitted:
                if isinstance(raw_id, bool):
                    continue
                try:
                    chunk_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if chunk_id in allowed_chunk_ids and chunk_id not in repaired:
                    repaired.append(chunk_id)
            # Never manufacture acceptable provenance. If none of the submitted
            # ids are trusted, leave the candidate unchanged for strict rejection.
            if repaired and repaired != submitted:
                item[field] = repaired
                removed_citations += len(submitted) - len(repaired)

        for group in _EXTRACTION_CLAIM_GROUPS:
            items = candidate.get(group)
            if isinstance(items, list):
                for item in items:
                    repair_ids(item, "source_chunk_ids")
        memory_updates = candidate.get("memory_updates")
        if isinstance(memory_updates, list):
            for update in memory_updates:
                repair_ids(update, "evidence_chunk_ids")
        if removed_citations:
            repairs.append(
                f"removed {removed_citations} unsupplied chunk citation(s)"
            )

    return candidate, tuple(repairs)


class ExtractionMention(StrictModel):
    entity_ref: MentionRef
    surface_form: str = Field(min_length=1, max_length=300)
    type: str = Field(
        min_length=1,
        max_length=40,
        json_schema_extra={"enum": sorted(ENTITY_TYPES)},
    )
    description: str = Field(default="", max_length=1000)
    provisional: bool = False

    @field_validator("type")
    @classmethod
    def valid_entity_type(cls, value: str) -> str:
        if value not in ENTITY_TYPES:
            raise ValueError("unknown entity type")
        return value


class ExtractionFact(StrictModel):
    entity_ref: EntityRef
    fact_type: str = Field(default="", max_length=80)
    content: str = Field(min_length=1, max_length=4000)
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionRelationship(StrictModel):
    source_ref: EntityRef
    target_ref: EntityRef
    relation_type: str = Field(default="", max_length=80)
    directed: bool = True
    content: str = Field(default="", max_length=4000)
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionEvent(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
    participant_refs: list[EntityRef] = Field(default_factory=list, max_length=100)
    location_ref: EntityRef | None = None
    significance: str = Field(default="", max_length=1000)
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionIdentityReveal(StrictModel):
    persona_ref: EntityRef
    true_entity_ref: EntityRef
    note: str = Field(default="", max_length=2000)
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionAlias(StrictModel):
    entity_ref: EntityRef
    alias: str = Field(min_length=1, max_length=300)
    is_reveal: bool = False
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class StateTransitionProposal(StrictModel):
    entity_ref: EntityRef
    state_key: str = Field(json_schema_extra={"enum": sorted(STATE_KEYS)})
    operation: Literal["set", "clear", "add", "remove", "confirm", "contradict"]
    value: Any = None
    value_entity_ref: EntityRef | None = None
    perspective_ref: EntityRef | None = None
    certainty: Literal["uncertain", "alleged", "presumed", "confirmed", "contradicted"] = "confirmed"
    narrative_scope: Literal["current", "historical", "dream", "prophecy", "alternate"] = "current"
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)

    @field_validator("state_key")
    @classmethod
    def valid_state_key(cls, value: str) -> str:
        if value not in STATE_KEYS:
            raise ValueError("unknown state key")
        return value


class RelationshipStateTransitionProposal(StrictModel):
    source_ref: EntityRef
    target_ref: EntityRef
    state_key: str = Field(
        json_schema_extra={"enum": sorted(RELATIONSHIP_STATE_KEYS)}
    )
    operation: Literal["set", "clear", "add", "remove", "confirm", "contradict"]
    value: Any = None
    certainty: Literal["uncertain", "alleged", "presumed", "confirmed", "contradicted"] = "confirmed"
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)

    @field_validator("state_key")
    @classmethod
    def valid_state_key(cls, value: str) -> str:
        if value not in RELATIONSHIP_STATE_KEYS:
            raise ValueError("unknown relationship state key")
        return value


class PlotThreadUpdateProposal(StrictModel):
    thread_ref: ThreadRef
    title: str | None = Field(default=None, max_length=300)
    operation: Literal["open", "advance", "clarify", "resolve", "reopen", "mark_dormant", "contradict"]
    summary: str = Field(min_length=1, max_length=3000)
    participant_refs: list[EntityRef] = Field(default_factory=list, max_length=100)
    keywords: list[Keyword] = Field(default_factory=list, max_length=50)
    certainty: Literal["uncertain", "alleged", "presumed", "confirmed", "contradicted"] = "confirmed"
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class MemoryCoverageBeat(StrictModel):
    chapter_refs: list[float] = Field(min_length=1, max_length=6)
    summary: str = Field(min_length=40, max_length=2000)


class MemoryUpdateProposal(StrictModel):
    kind: Literal["checkpoint", "volume"]
    # The trusted host renders the persisted summary from the distributed beats.
    # Keeping this nullable preserves a simple structured-output shape without
    # trusting a second, potentially endpoint-biased free-form reducer field.
    summary: str | None = Field(default=None, max_length=12_000)
    covered_chapters: list[float] = Field(min_length=1, max_length=1000)
    key_beats: list[MemoryCoverageBeat] = Field(min_length=1, max_length=200)
    evidence_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=500)


class ExtractionPayload(StrictModel):
    schema_version: Literal["2.2"] = "2.2"
    chapter: float
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mentions: list[ExtractionMention] = Field(default_factory=list, max_length=200)
    facts: list[ExtractionFact] = Field(default_factory=list, max_length=500)
    relationships: list[ExtractionRelationship] = Field(default_factory=list, max_length=300)
    events: list[ExtractionEvent] = Field(default_factory=list, max_length=300)
    identity_reveals: list[ExtractionIdentityReveal] = Field(default_factory=list, max_length=100)
    new_aliases: list[ExtractionAlias] = Field(default_factory=list, max_length=200)
    state_changes: list[StateTransitionProposal] = Field(default_factory=list, max_length=500)
    relationship_state_changes: list[RelationshipStateTransitionProposal] = Field(default_factory=list, max_length=300)
    thread_updates: list[PlotThreadUpdateProposal] = Field(default_factory=list, max_length=100)
    memory_updates: list[MemoryUpdateProposal] = Field(default_factory=list, max_length=2)
    warnings: list[WarningText] = Field(default_factory=list, max_length=100)


class DisambiguationDecision(StrictModel):
    case_ref: str
    decision: str
    confidence: Literal["low", "medium", "high"]
    evidence: str = Field(default="", max_length=500)


class DisambiguationPayload(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    decisions: list[DisambiguationDecision]


@dataclass(frozen=True)
class PreflightResult:
    healthy: bool
    version: str | None
    binary_sha256: str | None
    models: tuple[str, ...]
    plugin_version: str
    plugin_sha256: str | None
    plugin_valid: bool
    error_code: str | None = None
    error: str | None = None

    def public(self) -> dict:
        data = asdict(self)
        data["models"] = list(self.models)
        return data
