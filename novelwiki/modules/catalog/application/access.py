from __future__ import annotations

from novelwiki.kernel.errors import Forbidden, NotFound, ValidationFailed
from novelwiki.modules.identity.public import Principal

from ..domain.policies import can_edit, can_read
from ..domain.tags import clean_status_tags
from ..public import NovelAccess
from .ports import CatalogRepository


class CatalogAccessService:
    def __init__(self, repository: CatalogRepository):
        self._repository = repository

    async def get_novel(self, novel_id: int) -> NovelAccess | None:
        return await self._repository.get_access(novel_id)

    async def require_readable(
        self, novel_id: int, principal: Principal | None
    ) -> NovelAccess:
        novel = await self._repository.get_access(novel_id)
        if novel is None or not can_read(novel, principal):
            raise NotFound("Novel not found.")
        return novel

    async def require_editable(
        self, novel_id: int, principal: Principal | None
    ) -> NovelAccess:
        novel = await self._repository.get_access(novel_id)
        if novel is None or not can_read(novel, principal):
            raise NotFound("Novel not found.")
        if not can_edit(novel, principal):
            raise Forbidden("You don't have permission to edit this novel.")
        return novel

    async def add_to_library(self, novel_id: int, principal: Principal) -> None:
        await self.require_readable(novel_id, principal)
        await self._repository.add_to_library(novel_id, principal.user_id)

    async def remove_from_library(self, novel_id: int, principal: Principal) -> None:
        await self._repository.remove_from_library(novel_id, principal.user_id)

    async def set_visibility(
        self, novel_id: int, principal: Principal, requested: str
    ) -> str:
        visibility = (requested or "").strip().lower()
        allowed = {"private", "public", "global"}
        if visibility not in allowed:
            raise ValidationFailed(
                f"visibility must be one of {sorted(allowed)}."
            )
        novel = await self.require_editable(novel_id, principal)
        if (
            visibility == "global" or novel.visibility == "global"
        ) and not principal.is_admin:
            raise Forbidden("Only an admin can manage the Global library.")
        await self._repository.set_visibility(
            novel_id,
            visibility,
            steward_id=principal.user_id if visibility == "global" else None,
        )
        return visibility

    async def update_novel(
        self, novel_id: int, principal: Principal, requested_fields: dict
    ) -> str:
        fields = dict(requested_fields)
        if not fields:
            return "noop"
        novel = await self.require_readable(novel_id, principal)
        editor = can_edit(novel, principal)

        if "shelf" in fields:
            shelf = (fields.pop("shelf") or "").strip().lower()
            allowed_shelves = {"to_read", "reading", "completed"}
            if shelf and shelf not in allowed_shelves:
                raise ValidationFailed(f"Unknown shelf '{shelf}'.")
            await self._repository.set_shelf(
                novel_id, principal.user_id, shelf or None
            )

        if "status_tags" in fields:
            if not editor:
                raise Forbidden(
                    "Only the owner or an admin can change a novel's tags — "
                    "suggest them instead."
                )
            fields["status_tags"] = clean_status_tags(fields["status_tags"])

        if fields:
            if not editor:
                raise Forbidden("You don't have permission to edit this novel.")
            if (
                "contribution_policy" in fields
                and fields["contribution_policy"] not in ("manual", "auto")
            ):
                raise ValidationFailed(
                    "contribution_policy must be 'manual' or 'auto'."
                )
            await self._repository.update_metadata(novel_id, fields)
        return "success"
