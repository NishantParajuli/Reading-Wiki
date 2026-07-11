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
class ImportedNovelDraft:
    title: str
    author: str | None
    description: str | None
    original_language: str
    codex_enabled: bool
    series: str | None
    owner_id: int | None
    visibility: str


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
    async def create_novel(self, draft: NovelDraft, owner_id: int | None) -> int: ...
    async def add_to_library(self, novel_id: int, user_id: int) -> None: ...
    async def delete_novel(self, novel_id: int) -> None: ...
    async def enable_codex(self, novel_id: int) -> None: ...
    async def create_imported_novel(self, draft: ImportedNovelDraft) -> int: ...
    async def novel_exists(self, novel_id: int) -> bool: ...
    async def codex_enabled(self, novel_id: int) -> bool: ...
    async def set_cover_if_missing(self, novel_id: int, cover_url: str) -> None: ...
    async def touch_novel(self, novel_id: int) -> None: ...
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


def can_edit(novel: dict, user: dict | None) -> bool:
    from .adapters.inbound.access import can_edit as implementation

    return implementation(novel, user)


def is_admin(user: dict | None) -> bool:
    from .adapters.inbound.access import is_admin as implementation

    return implementation(user)


async def fetch_novel(novel_id: int) -> dict | None:
    from .adapters.inbound.access import fetch_novel as implementation

    return await implementation(novel_id)


async def require_readable(novel_id: int, user: dict | None) -> dict:
    from .adapters.inbound.access import require_readable as implementation

    return await implementation(novel_id, user)


def catalog_access_service(connection: object):
    from .adapters.outbound.postgres import PostgresCatalogRepository
    from .application import CatalogAccessService

    return CatalogAccessService(PostgresCatalogRepository(connection))
