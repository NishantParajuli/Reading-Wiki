from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from novelwiki.modules.ai_execution.application.contracts import (
    DisambiguationPayload,
    ExtractionPayload,
    StrictModel,
    TranslationSelfReview,
    TranslationTerm,
)


class CodexTranslationChapter(StrictModel):
    chapter_ref: str
    translated_title: str = Field(min_length=1, max_length=500)
    translation: str = Field(min_length=1)
    new_terms: list[TranslationTerm] = Field(default_factory=list, max_length=2000)
    self_review: TranslationSelfReview


class CodexTranslationResult(StrictModel):
    chapters: list[CodexTranslationChapter] = Field(min_length=1, max_length=10)


class CodexExtractionAudit(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class CodexExtractionResult(StrictModel):
    extraction: ExtractionPayload
    running_summary: str = Field(min_length=1, max_length=128_000)
    audit: CodexExtractionAudit


class CodexDisambiguationResult(DisambiguationPayload):
    pass


class CodexSmokeResult(StrictModel):
    ready: Literal["READY"]


RESULT_MODELS: dict[str, type[StrictModel]] = {
    "translate_batch": CodexTranslationResult,
    "codex_extract": CodexExtractionResult,
    "codex_verify": CodexExtractionResult,
    "entity_disambiguation": CodexDisambiguationResult,
    "smoke_test": CodexSmokeResult,
}


def output_schema(workload: str) -> dict[str, Any]:
    try:
        return RESULT_MODELS[workload].model_json_schema()
    except KeyError as exc:
        raise ValueError(f"unsupported OpenAI Codex workload: {workload}") from exc


def validate_result(workload: str, value: Any) -> StrictModel:
    try:
        model = RESULT_MODELS[workload]
    except KeyError as exc:
        raise ValueError(f"unsupported OpenAI Codex workload: {workload}") from exc
    return model.model_validate(value)

