from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class RequestedBackend(StrEnum):
    AUTO = "auto"
    API = "api"
    AGY = "agy"


class ExecutionBackend(StrEnum):
    API = "api"
    AGY = "agy"


class Workload(StrEnum):
    TRANSLATE_BATCH = "translate_batch"
    CODEX_EXTRACT = "codex_extract"
    SEGMENT_IMPORT = "segment_import"
    OCR_PAGES = "ocr_pages"
    ASK = "ask"
    PROFILE_SYNTHESIS = "profile_synthesis"


IMPLEMENTED_AGY_WORKLOADS = frozenset({Workload.TRANSLATE_BATCH, Workload.CODEX_EXTRACT})


@dataclass(frozen=True)
class BackendDecision:
    requested: RequestedBackend
    resolved: ExecutionBackend
    workload: Workload
    reason: str
    policy_version: int | None
    fallback_to_api: bool
    model: str | None

    def as_job_fields(self) -> dict:
        return {
            "backend_requested": self.requested.value,
            "execution_backend": self.resolved.value,
            "backend_policy_version": self.policy_version,
            "backend_fallback_allowed": self.fallback_to_api,
            "backend_model": self.model,
        }

    def public(self) -> dict:
        data = asdict(self)
        for key in ("requested", "resolved", "workload"):
            data[key] = data[key].value
        return data


def workload_for_job_kind(kind: str) -> Workload | None:
    return {
        "translate": Workload.TRANSLATE_BATCH,
        "codex_build": Workload.CODEX_EXTRACT,
    }.get(kind)
