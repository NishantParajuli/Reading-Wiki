from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


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


@dataclass(frozen=True)
class NovelDraft:
    title: str
    author: str | None = None
    description: str | None = None
    cover_url: str | None = None
    original_language: str = "en"
    codex_enabled: bool = False


@dataclass(frozen=True)
class TagSuggestionRecord:
    id: int
    from_user_id: int
    tags: tuple[str, ...]
    note: str | None
    status: str
    created_at: Any


class CatalogTransactionApi(Protocol):
    async def require_readable(self, novel_id: int, principal: object) -> NovelAccess: ...
    async def require_editable(self, novel_id: int, principal: object) -> NovelAccess: ...
    async def create_novel(self, draft: NovelDraft, owner_id: int) -> int: ...
    async def add_to_library(self, novel_id: int, user_id: int) -> None: ...
    async def delete_novel(self, novel_id: int) -> None: ...
    async def create_tag_suggestion(
        self, novel_id: int, from_user_id: int, tags: list[str], note: str | None
    ) -> int: ...
    async def list_tag_suggestions(
        self, novel_id: int, status: str
    ) -> list[TagSuggestionRecord]: ...
    async def accept_tag_suggestion(
        self, novel_id: int, suggestion_id: int, reviewed_by: int
    ) -> list[str]: ...
    async def reject_tag_suggestion(
        self, novel_id: int, suggestion_id: int, reviewed_by: int
    ) -> None: ...
