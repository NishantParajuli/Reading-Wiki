from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ScheduledJob:
    job_id: int
    created: bool


class WorkApi(Protocol):
    async def schedule(self, kind: str, **options: Any) -> ScheduledJob: ...
    async def cancel(self, job_id: int, user_id: int) -> None: ...


class WorkTransactionApi(Protocol):
    async def increment_quota_consumed(self, job_id: int, units: int) -> None: ...


@dataclass(frozen=True)
class JobQuotaSettlement:
    user_id: int | None
    novel_id: int | None
    quota_kind: str | None
    refundable_units: int


class WorkQuotaFinalizationTransactionApi(Protocol):
    async def finalize_quota(
        self, job_id: int, success: bool
    ) -> JobQuotaSettlement | None: ...
