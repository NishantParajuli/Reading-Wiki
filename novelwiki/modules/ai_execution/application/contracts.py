"""Stable DTOs exchanged with AI Execution clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class ExtractionPayload(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    chapter: float
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mentions: list[dict] = Field(default_factory=list, max_length=2000)
    facts: list[dict] = Field(default_factory=list, max_length=5000)
    relationships: list[dict] = Field(default_factory=list, max_length=3000)
    events: list[dict] = Field(default_factory=list, max_length=3000)
    identity_reveals: list[dict] = Field(default_factory=list, max_length=1000)
    new_aliases: list[dict] = Field(default_factory=list, max_length=2000)
    warnings: list[str] = Field(default_factory=list, max_length=100)


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
