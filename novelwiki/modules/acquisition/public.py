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


class AcquisitionTransactionApi(Protocol):
    async def create_source(self, novel_id: int, draft: SourceDraft) -> int: ...
    async def list_import_job_ids(self, novel_id: int) -> list[int]: ...
    async def store_novel_asset(
        self, novel_id: int, data: bytes, mime: str | None, kind: str
    ) -> dict[str, Any]: ...


class AcquisitionCleanupApi(Protocol):
    def cleanup_deleted_novel(self, novel_id: int, import_job_ids: list[int]) -> None: ...


class AcquisitionApi(Protocol):
    async def list_cleanup_targets(self, novel_id: int) -> tuple[str, ...]: ...
    async def cancel_import(self, job_id: int, user_id: int) -> None: ...
