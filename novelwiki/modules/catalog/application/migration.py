from __future__ import annotations

from collections.abc import Awaitable, Callable

from novelwiki.kernel.errors import Forbidden
from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.acquisition.public import (
    AcquisitionCleanupApi,
    AcquisitionTransactionApi,
    SourceDraft,
)
from novelwiki.modules.identity.public import Principal, UserDirectoryApi
from novelwiki.workflows.create_novel_with_source import create_novel_with_source
from novelwiki.workflows.delete_novel import delete_novel

from ..public import CatalogTransactionApi, NovelDraft


class CatalogMigrationService:
    """Application boundary for the final Catalog routes.

    The name is temporary only to distinguish this broader boundary from the pilot
    ``CatalogAccessService`` while callers are migrated. It contains no transport or SQL.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        validate_source_url: Callable[[str], Awaitable[str]],
        cleanup: AcquisitionCleanupApi,
    ):
        self._uow_factory = uow_factory
        self._validate_source_url = validate_source_url
        self._cleanup = cleanup

    async def create_novel(
        self,
        principal: Principal,
        novel: NovelDraft,
        source: SourceDraft | None,
    ) -> tuple[int, int | None]:
        if source is not None:
            source = SourceDraft(
                adapter=source.adapter,
                start_url=await self._validate_source_url(source.start_url),
                language=source.language,
                is_raw=source.is_raw,
                chapter_offset=source.chapter_offset,
                label=source.label,
                config=source.config,
            )
        return await create_novel_with_source(
            self._uow_factory, principal, novel, source
        )

    async def store_cover(
        self,
        novel_id: int,
        principal: Principal,
        data: bytes,
        mime: str | None,
    ) -> dict:
        async with self._uow_factory() as uow:
            catalog = uow.transaction.bind(CatalogTransactionApi)
            await catalog.require_editable(novel_id, principal)
            acquisition = uow.transaction.bind(AcquisitionTransactionApi)
            return await acquisition.store_novel_asset(
                novel_id, data, mime, "cover"
            )

    async def delete_novel(self, novel_id: int, principal: Principal) -> None:
        job_ids = await delete_novel(self._uow_factory, principal, novel_id)
        self._cleanup.cleanup_deleted_novel(novel_id, job_ids)

    async def suggest_tags(
        self,
        novel_id: int,
        principal: Principal,
        tags: list[str],
        note: str | None,
    ) -> int:
        async with self._uow_factory() as uow:
            catalog = uow.transaction.bind(CatalogTransactionApi)
            novel = await catalog.require_readable(novel_id, principal)
            if novel.owner_id == principal.user_id or principal.is_admin:
                from novelwiki.kernel.errors import ValidationFailed
                raise ValidationFailed("You can edit this novel's tags directly.")
            if novel.visibility not in ("public", "global"):
                raise Forbidden("Tags can only be suggested on shared novels.")
            return await catalog.create_tag_suggestion(
                novel_id, principal.user_id, tags, note
            )

    async def list_tag_suggestions(
        self, novel_id: int, principal: Principal, status: str
    ) -> list[dict]:
        async with self._uow_factory() as uow:
            catalog = uow.transaction.bind(CatalogTransactionApi)
            await catalog.require_editable(novel_id, principal)
            rows = await catalog.list_tag_suggestions(novel_id, status)
            directory = uow.transaction.bind(UserDirectoryApi)
            labels = await directory.labels({row.from_user_id for row in rows})
            return [
                {
                    "id": row.id,
                    "tags": list(row.tags),
                    "note": row.note,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "from_username": labels[row.from_user_id].username,
                    "from_display_name": labels[row.from_user_id].display_name,
                }
                for row in rows
            ]

    async def accept_tag_suggestion(
        self, novel_id: int, suggestion_id: int, principal: Principal
    ) -> list[str]:
        async with self._uow_factory() as uow:
            catalog = uow.transaction.bind(CatalogTransactionApi)
            await catalog.require_editable(novel_id, principal)
            return await catalog.accept_tag_suggestion(
                novel_id, suggestion_id, principal.user_id
            )

    async def reject_tag_suggestion(
        self, novel_id: int, suggestion_id: int, principal: Principal
    ) -> None:
        async with self._uow_factory() as uow:
            catalog = uow.transaction.bind(CatalogTransactionApi)
            await catalog.require_editable(novel_id, principal)
            await catalog.reject_tag_suggestion(
                novel_id, suggestion_id, principal.user_id
            )
