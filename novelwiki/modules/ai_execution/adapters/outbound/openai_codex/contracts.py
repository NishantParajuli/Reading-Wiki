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

def _scalar_json_schema() -> list[dict[str, str]]:
    return [
        {"type": "string"},
        {"type": "number"},
        {"type": "boolean"},
        {"type": "null"},
    ]


def _strict_json_schema(value: Any) -> Any:
    """Convert Pydantic JSON Schema into the strict Structured Outputs subset."""
    if isinstance(value, list):
        return [_strict_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {
        key: _strict_json_schema(item)
        for key, item in value.items()
        if key != "default"
    }
    properties = normalized.get("properties")
    if isinstance(properties, dict):
        normalized["required"] = list(properties)
        normalized["additionalProperties"] = False
    elif set(normalized) <= {"title", "description"}:
        normalized["anyOf"] = [
            *_scalar_json_schema(),
            {"type": "array", "items": {"anyOf": _scalar_json_schema()}},
        ]
    return normalized


def output_schema(workload: str) -> dict[str, Any]:
    try:
        return _strict_json_schema(RESULT_MODELS[workload].model_json_schema())
    except KeyError as exc:
        raise ValueError(f"unsupported OpenAI Codex workload: {workload}") from exc


def validate_result(workload: str, value: Any) -> StrictModel:
    try:
        model = RESULT_MODELS[workload]
    except KeyError as exc:
        raise ValueError(f"unsupported OpenAI Codex workload: {workload}") from exc
    return model.model_validate(value)
