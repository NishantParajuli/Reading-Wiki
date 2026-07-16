"""Stable DTOs exchanged with AI Execution clients."""

from __future__ import annotations

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
    term_type: str = Field(default="term", min_length=1, max_length=40)

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


class ExtractionMention(StrictModel):
    entity_ref: MentionRef
    surface_form: str = Field(min_length=1, max_length=300)
    type: str = Field(min_length=1, max_length=40)
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
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionRelationship(StrictModel):
    source_ref: EntityRef
    target_ref: EntityRef
    relation_type: str = Field(default="", max_length=80)
    directed: bool = True
    content: str = Field(default="", max_length=4000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionEvent(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
    participant_refs: list[EntityRef] = Field(default_factory=list, max_length=100)
    location_ref: EntityRef | None = None
    significance: str = Field(default="", max_length=1000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionIdentityReveal(StrictModel):
    persona_ref: EntityRef
    true_entity_ref: EntityRef
    note: str = Field(default="", max_length=2000)
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class ExtractionAlias(StrictModel):
    entity_ref: EntityRef
    alias: str = Field(min_length=1, max_length=300)
    is_reveal: bool = False
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class StateTransitionProposal(StrictModel):
    entity_ref: EntityRef
    state_key: str
    operation: Literal["set", "clear", "add", "remove", "confirm", "contradict"]
    value: Any = None
    value_entity_ref: EntityRef | None = None
    perspective_ref: EntityRef | None = None
    certainty: Literal["uncertain", "alleged", "presumed", "confirmed", "contradicted"] = "confirmed"
    narrative_scope: Literal["current", "historical", "dream", "prophecy", "alternate"] = "current"
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
    state_key: str
    operation: Literal["set", "clear", "add", "remove", "confirm", "contradict"]
    value: Any = None
    certainty: Literal["uncertain", "alleged", "presumed", "confirmed", "contradicted"] = "confirmed"
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
    source_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=50)


class MemoryUpdateProposal(StrictModel):
    kind: Literal["checkpoint", "volume"]
    summary: str = Field(min_length=1, max_length=12_000)
    evidence_chunk_ids: list[PositiveInt] = Field(min_length=1, max_length=500)


class ExtractionPayload(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
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
