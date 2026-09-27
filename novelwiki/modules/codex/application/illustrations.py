from __future__ import annotations

import json
import math

from novelwiki.kernel.errors import (
    ApplicationError,
    Conflict,
    NotFound,
    ValidationFailed,
)
from ..domain.illustrations import STYLES, source_hash


class IllustrationSourceChanged(Conflict):
    code = "illustration_source_changed"
    safe_detail = "Chapter or character sheet changed - request a fresh set"


def metadata(row):
    value = row.get("metadata") or {}
    return json.loads(value) if isinstance(value, str) else value


def complete_scenes(rows):
    """Pick the newest complete batch per style, in story order."""
    batches = {}
    for row in rows:
        if row["kind"] == "scene":
            meta = metadata(row)
            batches.setdefault((row["style"], meta.get("batch")), []).append(row)
    selected, styles = [], set()
    for (style, _batch), scenes in batches.items():
        count = metadata(scenes[0]).get("count")
        if style in styles or count not in (1, 2, 3):
            continue
        if len(scenes) != count or {
            metadata(row).get("index") for row in scenes
        } != set(range(count)):
            continue
        styles.add(style)
        selected.extend(sorted(scenes, key=lambda row: metadata(row)["index"]))
    return selected


class IllustrationService:
    def __init__(
        self,
        *,
        access,
        snapshot,
        store,
        grant,
        schedule,
        latest,
        manage_access=None,
        chapters=None,
        schedule_range=None,
    ):
        self.access, self.snapshot, self.store = access, snapshot, store
        self.grant, self.schedule, self.latest = grant, schedule, latest
        self.manage_access, self.chapters, self.schedule_range = (
            manage_access,
            chapters,
            schedule_range,
        )

    async def chapter(self, novel_id, chapter, principal, *, edit=False):
        if not math.isfinite(chapter) or chapter < 0:
            raise ValidationFailed("Choose a valid chapter.")
        await self.access(novel_id, chapter, principal, edit=edit)
        snapshot = await self.snapshot(novel_id, chapter)
        if not snapshot or not (snapshot.get("content") or "").strip():
            raise NotFound("This chapter has no translated text to illustrate yet.")
        return snapshot

    async def _current(self, row, hashes):
        number = float(row["chapter"])
        if number not in hashes:
            snapshot = await self.snapshot(row["novel_id"], number)
            hashes[number] = (
                source_hash(snapshot) if snapshot and snapshot.get("content") else None
            )
        if hashes[number] != row["source_hash"]:
            return False
        for source in metadata(row).get("sources", []):
            source_number = float(source["chapter"])
            if source_number not in hashes:
                snapshot = await self.snapshot(row["novel_id"], source_number)
                hashes[source_number] = (
                    source_hash(snapshot)
                    if snapshot and snapshot.get("content")
                    else None
                )
            if hashes[source_number] != source["source_hash"]:
                return False
        if row["kind"] == "scene":
            for art_id in metadata(row).get("references", []):
                reference = await self.store.get(row["novel_id"], art_id, images=False)
                if (
                    not reference
                    or reference["kind"] != "reference"
                    or reference["style"] != row["style"]
                    or float(reference["chapter"]) > number
                    or not await self._current(reference, hashes)
                ):
                    return False
        return True

    async def current_rows(self, novel_id, chapter, *, images=False):
        rows = await self.store.list(novel_id, chapter, images=images)
        hashes = {}
        return [row for row in rows if await self._current(row, hashes)]

    async def list(self, novel_id, chapter, principal):
        await self.chapter(novel_id, chapter, principal)
        can_generate, reason = False, None
        try:
            await self.access(novel_id, chapter, principal, edit=True)
            await self.grant(principal)
            can_generate = True
        except ApplicationError as exc:
            reason = str(exc)
        rows = await self.current_rows(novel_id, chapter)
        selected = complete_scenes(rows)
        seen = set()
        for row in sorted(rows, key=lambda item: float(item["chapter"]), reverse=True):
            if row["kind"] != "reference":
                continue
            key = (row["style"], row["character_key"])
            if key not in seen:
                seen.add(key)
                selected.append(row)
        items = []
        for row in selected:
            meta = metadata(row)
            items.append(
                {
                    "id": str(row["id"]),
                    "kind": row["kind"],
                    "title": row["title"],
                    "caption": row["caption"],
                    "style": row["style"],
                    "chapter": float(row["chapter"]),
                    "prompt": meta.get("prompt", ""),
                    "design_notes": meta.get("design_notes", ""),
                    "placement": meta.get("placement"),
                    "evidence": meta.get("evidence", ""),
                    "image_url": f"/api/novels/{novel_id}/illustrations/{row['id']}/image",
                }
            )
        latest = await self.latest(novel_id, chapter, principal.user_id)
        return {
            "items": items,
            "can_generate": can_generate,
            "unavailable_reason": reason,
            "active_job": latest if latest and latest["status"] != "done" else None,
        }

    async def generate(
        self, novel_id, chapter, principal, *, count=None, style="luminous", force=False
    ):
        if count not in (None, 1, 2, 3) or style not in STYLES:
            raise ValidationFailed(
                "Choose 1–3 images and an available illustration style."
            )
        snapshot = await self.chapter(novel_id, chapter, principal, edit=True)
        if len(snapshot["content"]) > 150_000:
            raise ValidationFailed(
                "This chapter is too long to illustrate in one request."
            )
        decision = await self.grant(principal)
        digest = source_hash(snapshot)
        if not force:
            scenes = [
                row
                for row in complete_scenes(await self.current_rows(novel_id, chapter))
                if row["style"] == style
            ]
            if scenes and (count is None or len(scenes) >= count):
                return {"job_id": metadata(scenes[0])["batch"], "already_created": True}
        return await self.schedule(
            novel_id, chapter, principal, count, style, digest, decision
        )

    async def range_info(self, novel_id, principal):
        await self.manage_access(novel_id, principal)
        can_generate, reason = False, None
        try:
            await self.grant(principal)
            can_generate = True
        except ApplicationError as exc:
            reason = str(exc)
        latest = await self.latest(novel_id, None, principal.user_id)
        return {
            "can_generate": can_generate,
            "unavailable_reason": reason,
            "active_job": latest,
        }

    async def generate_range(
        self,
        novel_id,
        principal,
        *,
        from_chapter,
        to_chapter,
        style="luminous",
        force=False,
    ):
        if (
            not math.isfinite(from_chapter)
            or not math.isfinite(to_chapter)
            or from_chapter < 0
            or to_chapter < from_chapter
            or style not in STYLES
        ):
            raise ValidationFailed(
                "Choose a valid chapter range and illustration style."
            )
        # Managing art ahead of reading is an explicit owner/admin action. It does
        # not advance reading progress or relax access to the resulting images.
        await self.manage_access(novel_id, principal)
        decision = await self.grant(principal)
        numbers = await self.chapters(
            novel_id,
            start=from_chapter,
            end=to_chapter,
            require_content=True,
            narrative_only=True,
        )
        if not numbers:
            raise NotFound("This range has no translated story chapters to illustrate.")
        if len(numbers) > 1000:
            raise ValidationFailed(
                "Choose up to 1,000 translated chapters per illustration batch."
            )
        chapters = []
        for number in numbers:
            snapshot = await self.snapshot(novel_id, number)
            if not snapshot or not (snapshot.get("content") or "").strip():
                raise IllustrationSourceChanged(
                    "A chapter in this range changed. Choose the range again."
                )
            if len(snapshot["content"]) > 150_000:
                raise ValidationFailed(
                    f"Chapter {number:g} is too long to illustrate in one request."
                )
            chapters.append({"chapter": number, "source_hash": source_hash(snapshot)})
        return await self.schedule_range(
            novel_id, principal, chapters, style, force, decision
        )

    async def image(self, novel_id, art_id, principal):
        row = await self.store.get(novel_id, art_id)
        if row is None:
            raise NotFound("Illustration not found.")
        await self.chapter(novel_id, float(row["chapter"]), principal)
        if not await self._current(row, {}):
            raise NotFound(
                "This illustration belongs to an older chapter or character-sheet version."
            )
        return row["image"]
