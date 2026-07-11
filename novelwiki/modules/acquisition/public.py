from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceDraft:
    adapter: str
    start_url: str
    language: str = "en"
    is_raw: bool = False
    chapter_offset: float = 0
    label: str | None = None
    config: dict | None = None


@dataclass(frozen=True)
class ImportNovelDraft:
    title: str
    author: str | None
    description: str | None
    original_language: str
    codex_enabled: bool
    series: str | None
    owner_id: int | None
    visibility: str


class AcquisitionTransactionApi(Protocol):
    async def create_source(self, novel_id: int, draft: SourceDraft) -> int: ...
    async def list_import_job_ids(self, novel_id: int) -> list[int]: ...
    async def store_novel_asset(
        self, novel_id: int, data: bytes, mime: str | None, kind: str
    ) -> dict[str, Any]: ...
    async def source_offset_state(
        self, source_id: int
    ) -> tuple[int, float]: ...
    async def set_source_offset(self, source_id: int, offset: float) -> None: ...
    async def import_source(self, source_id: int) -> dict[str, Any] | None: ...
    async def replace_import_source(
        self, source_id: int, *, adapter: str, start_url: str, language: str,
        is_raw: bool, offset: float, label: str,
    ) -> None: ...
    async def create_import_source(
        self, novel_id: int, *, adapter: str, start_url: str, language: str,
        is_raw: bool, offset: float, label: str,
    ) -> int: ...
    async def commit_import_asset(
        self, novel_id: int, job_id: int, sha256: str, extension: str,
        mime: str | None, kind: str, width: int | None, height: int | None,
    ) -> dict[str, Any]: ...
    async def finalize_import_job(
        self, job_id: int, novel_id: int, source_id: int, stats: dict
    ) -> None: ...


class AcquisitionCleanupApi(Protocol):
    def cleanup_deleted_novel(self, novel_id: int, import_job_ids: list[int]) -> None: ...


class AcquisitionApi(Protocol):
    async def list_cleanup_targets(self, novel_id: int) -> tuple[str, ...]: ...
    async def cancel_import(self, job_id: int, user_id: int) -> None: ...


async def cancel_import_job(job_id: int, user_id: int) -> bool:
    from .adapters.inbound.worker import cancel_job

    return await cancel_job(job_id, user_id)


async def list_import_jobs(**filters) -> list[dict]:
    from .adapters.inbound.worker import list_jobs

    return await list_jobs(**filters)
