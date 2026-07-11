from __future__ import annotations

from novelwiki.kernel.errors import Conflict, NotFound
from novelwiki.modules.identity.public import Principal

from ..domain.tags import clean_status_tags
from ..public import NovelAccess, NovelDraft, TagSuggestionRecord
from .access import CatalogAccessService
from .ports import CatalogRepository


class CatalogTransactionService:
    """Catalog commands bound to the workflow's active database transaction."""

    def __init__(self, repository: CatalogRepository):
        self._repository = repository
        self._access = CatalogAccessService(repository)

    async def require_readable(self, novel_id: int, principal: object) -> NovelAccess:
        return await self._access.require_readable(novel_id, principal)

    async def require_editable(self, novel_id: int, principal: object) -> NovelAccess:
        return await self._access.require_editable(novel_id, principal)

    async def create_novel(self, draft: NovelDraft, owner_id: int) -> int:
        return await self._repository.create_novel(draft, owner_id)

    async def add_to_library(self, novel_id: int, user_id: int) -> None:
        await self._repository.add_to_library(novel_id, user_id)

    async def delete_novel(self, novel_id: int) -> None:
        await self._repository.delete_novel(novel_id)

    async def create_tag_suggestion(
        self, novel_id: int, from_user_id: int, tags: list[str], note: str | None
    ) -> int:
        return await self._repository.create_tag_suggestion(
            novel_id, from_user_id, clean_status_tags(tags), (note or "").strip() or None
        )

    async def list_tag_suggestions(
        self, novel_id: int, status: str
    ) -> list[TagSuggestionRecord]:
        return await self._repository.list_tag_suggestions(novel_id, status)

    async def accept_tag_suggestion(
        self, novel_id: int, suggestion_id: int, reviewed_by: int
    ) -> list[str]:
        suggestion = await self._repository.get_tag_suggestion(novel_id, suggestion_id)
        if suggestion is None:
            raise NotFound("Tag suggestion not found.")
        tags, status = suggestion
        if status != "pending":
            raise Conflict(f"Suggestion is already '{status}'.")
        cleaned = clean_status_tags(tags)
        await self._repository.apply_tags(novel_id, cleaned)
        await self._repository.review_tag_suggestion(suggestion_id, "accepted", reviewed_by)
        return cleaned

    async def reject_tag_suggestion(
        self, novel_id: int, suggestion_id: int, reviewed_by: int
    ) -> None:
        suggestion = await self._repository.get_tag_suggestion(novel_id, suggestion_id)
        if suggestion is None or suggestion[1] != "pending":
            raise NotFound("No pending tag suggestion with that id.")
        await self._repository.review_tag_suggestion(suggestion_id, "rejected", reviewed_by)
