from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from novelwiki.kernel.errors import Conflict, NotFound, ValidationFailed
from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.catalog.public import CatalogTransactionApi
from novelwiki.modules.identity.public import Principal, UserDirectoryApi

from ..public import ReadingTransactionApi
from .dto import ChapterListItem, ServedChapter
from .ports import ChapterTranslationPort, SelfTranslationQuotaPort, SourceMetadataPort


class ReadingMigrationService:
    """Application boundary for chapters, overlays, and contributions."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        translation: ChapterTranslationPort,
        quota: SelfTranslationQuotaPort,
        prefetch_count: int,
    ):
        self._uow_factory = uow_factory
        self._translation = translation
        self._quota = quota
        self._prefetch_count = prefetch_count

    async def list_chapters(
        self, novel_id: int, principal: Principal | None
    ) -> list[ChapterListItem]:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_readable(
                novel_id, principal
            )
            return await uow.transaction.bind(ReadingTransactionApi).list_chapters(
                novel_id
            )

    async def get_chapter(
        self, novel_id: int, number: float, principal: Principal | None
    ) -> ServedChapter:
        async with self._uow_factory() as uow:
            novel = await uow.transaction.bind(
                CatalogTransactionApi
            ).require_readable(novel_id, principal)
            snapshot = await uow.transaction.bind(ReadingTransactionApi).get_chapter(
                novel_id, number, principal.user_id if principal is not None else None
            )
            source = await uow.transaction.bind(SourceMetadataPort).source_metadata(
                snapshot.source_id
            )
            snapshot = replace(
                snapshot, adapter=source.get("adapter"),
                source_is_raw=bool(source.get("is_raw")),
            )

        content = snapshot.content
        status = snapshot.translation_status
        translated = snapshot.is_translated
        prefetch_after = None
        if content is None and snapshot.has_original:
            result = await self._translation.translate_chapter(
                novel_id, number, principal
            )
            content = result.get("content")
            status = result.get("status")
            translated = status == "done"
            if status == "done":
                prefetch_after = number
        return ServedChapter(
            snapshot=snapshot,
            novel=novel,
            content=content,
            translation_status=status,
            is_translated=translated,
            prefetch_after=prefetch_after,
        )

    async def prefetch(
        self, novel_id: int, after_number: float, principal: Principal | None
    ) -> None:
        await self._translation.prefetch(
            novel_id, after_number, self._prefetch_count, principal
        )

    async def edit_base_content(
        self, novel_id: int, number: float, content: str, principal: Principal
    ) -> int:
        text = (content or "").strip()
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_editable(
                novel_id, principal
            )
            if not text:
                raise ValidationFailed("Content can't be empty.")
            reading = uow.transaction.bind(ReadingTransactionApi)
            await reading.chapter_version_and_source(novel_id, number)
            return await reading.update_base_content(novel_id, number, text)

    async def save_overlay(
        self, novel_id: int, number: float, content: str, principal: Principal
    ) -> None:
        text = (content or "").strip()
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_readable(
                novel_id, principal
            )
            if not text:
                raise ValidationFailed("Content can't be empty.")
            reading = uow.transaction.bind(ReadingTransactionApi)
            version, _ = await reading.chapter_version_and_source(novel_id, number)
            await reading.save_overlay(
                novel_id, number, principal.user_id, text, version, "manual_edit"
            )

    async def delete_overlay(
        self, novel_id: int, number: float, principal: Principal
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_readable(
                novel_id, principal
            )
            await uow.transaction.bind(ReadingTransactionApi).delete_overlay(
                novel_id, number, principal.user_id
            )

    async def resolve_overlay(
        self,
        novel_id: int,
        number: float,
        choice: str,
        content: str | None,
        principal: Principal,
    ) -> None:
        normalized = (choice or "").lower()
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_readable(
                novel_id, principal
            )
            if normalized not in ("base", "mine", "merge"):
                raise ValidationFailed("choice must be 'base', 'mine', or 'merge'.")
            reading = uow.transaction.bind(ReadingTransactionApi)
            version, _ = await reading.chapter_version_and_source(novel_id, number)
            if normalized == "base":
                await reading.delete_overlay(novel_id, number, principal.user_id)
            elif normalized == "mine":
                await reading.reanchor_overlay(
                    novel_id, number, principal.user_id, version
                )
            else:
                text = (content or "").strip()
                if not text:
                    raise ValidationFailed("A merge needs the resolved content.")
                await reading.save_overlay(
                    novel_id, number, principal.user_id, text, version, "manual_edit"
                )

    async def self_translate(
        self, novel_id: int, number: float, principal: Principal
    ) -> str:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_readable(
                novel_id, principal
            )
            version, has_source = await uow.transaction.bind(
                ReadingTransactionApi
            ).chapter_version_and_source(novel_id, number)
        if not has_source:
            raise Conflict("This chapter has no source text to translate.")
        await self._quota.check_and_reserve(
            principal, "translated_chapters", 1
        )
        translation = await self._translation.translate_raw_chapter(
            novel_id, number
        )
        if not translation:
            raise Conflict("This chapter could not be translated.")
        async with self._uow_factory() as uow:
            await uow.transaction.bind(ReadingTransactionApi).save_overlay(
                novel_id, number, principal.user_id, translation, version,
                "self_translated",
            )
        return translation

    async def contribute(
        self, novel_id: int, number: float, principal: Principal
    ) -> tuple[str, int]:
        async with self._uow_factory() as uow:
            novel = await uow.transaction.bind(
                CatalogTransactionApi
            ).require_readable(novel_id, principal)
            reading = uow.transaction.bind(ReadingTransactionApi)
            overlay = await reading.get_overlay(
                novel_id, number, principal.user_id
            )
            if overlay is None:
                raise Conflict("You have no edit to offer for this chapter.")
            content, base_version = overlay
            version, _ = await reading.chapter_version_and_source(novel_id, number)
            auto = novel.contribution_policy == "auto" and base_version >= version
            status = "auto_merged" if auto else "pending"
            contribution_id = await reading.create_contribution(
                novel_id, number, principal.user_id, content, base_version,
                status, auto,
            )
            if auto:
                await reading.update_base_content(
                    novel_id, number, content,
                    keep_overlay_user=principal.user_id,
                )
            return status, contribution_id

    async def list_contributions(
        self, novel_id: int, status: str, principal: Principal
    ) -> list[dict]:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_editable(
                novel_id, principal
            )
            rows = await uow.transaction.bind(
                ReadingTransactionApi
            ).list_contributions(novel_id, status)
            labels = await uow.transaction.bind(UserDirectoryApi).labels(
                {row.from_user_id for row in rows}
            )
            return [
                {
                    "id": row.id,
                    "chapter": row.chapter,
                    "content": row.content,
                    "base_version": row.base_version,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "from_username": labels[row.from_user_id].username,
                    "from_display_name": labels[row.from_user_id].display_name,
                    "base_content": row.base_content,
                    "is_conflict": (
                        row.current_content_version is not None
                        and row.base_version < row.current_content_version
                    ),
                }
                for row in rows
            ]

    async def accept_contribution(
        self,
        novel_id: int,
        contribution_id: int,
        resolved_content: str | None,
        principal: Principal,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_editable(
                novel_id, principal
            )
            reading = uow.transaction.bind(ReadingTransactionApi)
            contribution = await reading.get_contribution(
                novel_id, contribution_id
            )
            if contribution is None:
                raise NotFound("Contribution not found.")
            chapter, offered, contributor_id, base_version, status = contribution
            if status != "pending":
                raise Conflict(f"Contribution is already '{status}'.")
            current_version, _ = await reading.chapter_version_and_source(
                novel_id, chapter
            )
            resolved = (resolved_content or "").strip()
            if base_version < current_version and not resolved:
                raise Conflict(
                    "This contribution conflicts with the current base. "
                    "Provide resolved content to accept it."
                )
            content = resolved or offered
            await reading.update_base_content(
                novel_id, chapter, content, keep_overlay_user=contributor_id
            )
            await reading.mark_contribution_accepted(
                contribution_id, principal.user_id, content
            )

    async def reject_contribution(
        self, novel_id: int, contribution_id: int, principal: Principal
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_editable(
                novel_id, principal
            )
            updated = await uow.transaction.bind(
                ReadingTransactionApi
            ).reject_contribution(novel_id, contribution_id, principal.user_id)
            if not updated:
                raise NotFound("No pending contribution with that id.")
