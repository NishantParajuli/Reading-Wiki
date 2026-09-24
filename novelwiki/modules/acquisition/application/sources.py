from __future__ import annotations

from dataclasses import dataclass
import json
import math

from novelwiki.kernel.errors import Conflict, NotFound, ValidationFailed
from novelwiki.modules.identity.public import Principal

from ..public import SourceDraft
from .ports import (
    AcquisitionRepository,
    AssetFile,
    AssetFilesystemPort,
    CatalogAccessPort,
    ScrapeWorkPort,
    SourceOffsetPort,
    SourceUrlPort,
    SpendPolicyPort,
)


@dataclass(frozen=True)
class ScheduleScrape:
    source_id: int | None = None
    force: bool = False
    max_chapters: int | None = None


def _validate_source_config(config: object) -> None:
    if not isinstance(config, dict):
        raise ValidationFailed("Source config must be an object.")
    if "archive_password" in config and not isinstance(config["archive_password"], str):
        raise ValidationFailed("The RAW ZIP password must be text; use an empty string to clear it.")
    try:
        # JSONB rejects non-finite numbers, NULs and unpaired Unicode surrogates.
        # Check before the separately composed offset workflow can renumber data.
        json.dumps(config, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ValidationFailed("Source config must contain valid JSON values.") from None
    pending = [config]
    while pending:
        value = pending.pop()
        if isinstance(value, str) and "\x00" in value:
            raise ValidationFailed("Source config cannot contain null characters.")
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


def _validate_source_offset(offset: object) -> None:
    try:
        valid_offset = math.isfinite(float(offset))
    except (TypeError, ValueError, OverflowError):
        valid_offset = False
    if not valid_offset:
        raise ValidationFailed("Chapter offset must be a finite number.")


def _validate_source_text(value: object, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValidationFailed(f"Source {field} must be text or null.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValidationFailed(f"Source {field} must contain valid Unicode text.") from None
    if "\x00" in value:
        raise ValidationFailed(f"Source {field} cannot contain null characters.")


def validate_source_draft(draft: SourceDraft) -> None:
    """Shared validation for standalone and transactional source creation."""
    _validate_source_offset(draft.chapter_offset)
    if draft.config is not None:
        _validate_source_config(draft.config)
    for field in ("start_url", "label", "language"):
        _validate_source_text(getattr(draft, field), field)


class AcquisitionService:
    """Source lifecycle, scrape scheduling, and authenticated Acquisition assets."""

    def __init__(
        self,
        repository: AcquisitionRepository,
        catalog: CatalogAccessPort,
        source_urls: SourceUrlPort,
        spend_policy: SpendPolicyPort,
        work: ScrapeWorkPort,
        filesystem: AssetFilesystemPort,
        source_offsets: SourceOffsetPort | None = None,
    ):
        self._repository = repository
        self._catalog = catalog
        self._source_urls = source_urls
        self._spend_policy = spend_policy
        self._work = work
        self._filesystem = filesystem
        self._source_offsets = source_offsets

    async def add_source(
        self, novel_id: int, principal: Principal, draft: SourceDraft
    ) -> int:
        await self._catalog.require_editable(novel_id, principal)
        validate_source_draft(draft)
        start_url = await self._source_urls.validate(draft.start_url)
        return await self._repository.create_source(
            novel_id,
            SourceDraft(
                adapter=draft.adapter,
                start_url=start_url,
                language=draft.language,
                is_raw=draft.is_raw,
                chapter_offset=draft.chapter_offset,
                label=draft.label,
                config=draft.config,
            ),
        )

    async def update_source(
        self,
        novel_id: int,
        source_id: int,
        principal: Principal,
        requested_fields: dict[str, object],
    ) -> tuple[str, int]:
        await self._catalog.require_editable(novel_id, principal)
        fields = dict(requested_fields)
        if not fields:
            return "noop", 0
        # Validate the full update before offset renumbering can write anything.
        if not set(fields) <= {"chapter_offset", "start_url", "label", "language", "is_raw", "config"}:
            raise ValidationFailed("Unsupported source fields.")
        if "config" in fields:
            _validate_source_config(fields["config"])
        if "chapter_offset" in fields:
            _validate_source_offset(fields["chapter_offset"])
        for field in ("start_url", "label", "language"):
            if field in fields:
                _validate_source_text(fields[field], field)
        if "is_raw" in fields and fields["is_raw"] is not None and not isinstance(fields["is_raw"], bool):
            raise ValidationFailed("Source is_raw must be a boolean or null.")
        if "start_url" in fields and fields["start_url"] is not None:
            fields["start_url"] = await self._source_urls.validate(str(fields["start_url"]))
        if not await self._repository.source_exists(novel_id, source_id):
            raise NotFound("Source not found.")
        try:
            renumbered = 0
            if "chapter_offset" in fields and self._source_offsets is not None:
                renumbered = await self._source_offsets.update(
                    source_id, float(fields.pop("chapter_offset"))
                )
            if fields:
                renumbered += await self._repository.update_source(source_id, fields)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc
        except Exception as exc:
            raise Conflict(f"Could not update source: {exc}") from exc
        return "success", renumbered

    async def schedule_scrape(
        self, novel_id: int, principal: Principal, command: ScheduleScrape
    ) -> dict:
        await self._catalog.require_editable(novel_id, principal)
        self._spend_policy.ensure_allowed(principal)
        if command.max_chapters is not None and command.max_chapters < 1:
            raise ValidationFailed("Maximum chapters must be a positive integer.")
        if command.source_id is not None:
            if not await self._repository.source_exists(novel_id, command.source_id):
                raise NotFound("Source not found.")
            target = f"source{command.source_id}"
        else:
            target = "all"
        idem = (
            f"scrape:novel{novel_id}:{target}:"
            f"force{int(command.force)}:max{command.max_chapters}"
        )
        job_id, created = await self._work.schedule(
            novel_id=novel_id,
            user_id=principal.user_id,
            options={
                "source_id": command.source_id,
                "force": command.force,
                "max_chapters": command.max_chapters,
            },
            idempotency_key=idem,
        )
        return {
            "status": "success",
            "message": (
                "Scrape job scheduled."
                if created
                else "A scrape for this target is already running."
            ),
            "job_id": job_id,
            "deduped": not created,
        }

    async def novel_asset(
        self, novel_id: int, filename: str, principal: Principal
    ) -> AssetFile:
        await self._catalog.require_readable(novel_id, principal)
        sha256, extension, safe_name = self._filesystem.normalize_filename(filename)
        relative_path = self._filesystem.novel_relative_path(
            novel_id, sha256, extension
        )
        asset = await self._repository.novel_asset(
            novel_id, sha256, relative_path
        )
        if asset is None:
            raise NotFound("Asset not found.")
        _stored_path, mime = asset
        return self._filesystem.novel_file(novel_id, safe_name, mime)

    async def import_job_asset(
        self, job_id: int, filename: str, principal: Principal
    ) -> AssetFile:
        owner = await self._repository.import_asset_owner(job_id)
        if owner is None or (
            not principal.is_admin and owner.user_id != principal.user_id
        ):
            raise NotFound("Import job not found.")
        sha256, _extension, safe_name = self._filesystem.normalize_filename(filename)
        cover_sha = str(owner.detected_meta.get("cover_sha") or "").lower()
        if cover_sha and cover_sha != sha256:
            raise NotFound("Asset not found.")
        return self._filesystem.staged_file(job_id, safe_name)
