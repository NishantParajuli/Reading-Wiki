from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ScheduledJob:
    job_id: int
    created: bool


class WorkApi(Protocol):
    async def schedule(self, kind: str, **options) -> ScheduledJob: ...
    async def cancel(self, job_id: int, user_id: int) -> None: ...
