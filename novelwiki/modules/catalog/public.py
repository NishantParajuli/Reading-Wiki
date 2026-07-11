from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class NovelAccess:
    novel_id: int
    owner_id: int | None
    visibility: str
    contribution_policy: str | None = None
    title: str | None = None
    description: str | None = None


class CatalogAccess(Protocol):
    async def require_readable(self, novel_id: int, principal: object) -> NovelAccess: ...
    async def require_editable(self, novel_id: int, principal: object) -> NovelAccess: ...
