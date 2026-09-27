"""Sequential, resumable range generation sharing character identities across chapters."""

from __future__ import annotations

from .illustrations import IllustrationSourceChanged, complete_scenes, metadata
from ..domain.illustrations import current_style, source_hash


class IllustrationBatchWorker:
    def __init__(
        self, *, store, snapshot, current_rows, execute_chapter, progress, cancel
    ):
        self.store, self.snapshot, self.current_rows = store, snapshot, current_rows
        self.execute_chapter, self.progress, self.cancel = (
            execute_chapter,
            progress,
            cancel,
        )

    async def execute(self, job):
        options = job["options"]
        chapters = options["chapters"]
        total = len(chapters)
        # Check even completed chapters before resuming, so an edited range cannot
        # silently combine old art with newly planned later scenes.
        for item in chapters:
            await self.cancel(job["id"])
            snapshot = await self.snapshot(job["novel_id"], item["chapter"])
            if (
                not snapshot
                or not snapshot.get("content")
                or source_hash(snapshot) != item["source_hash"]
            ):
                raise IllustrationSourceChanged(
                    "A chapter in this range changed. Request a fresh range."
                )
        parent = await self.store.plan(job["id"])
        if parent is None:
            if (job.get("progress") or {}).get("range_started"):
                raise IllustrationSourceChanged(
                    "Illustration range was invalidated. Request a fresh range."
                )
            parent = await self.store.save_plan(
                job["id"],
                {
                    "novel_id": job["novel_id"],
                    "chapter": chapters[0]["chapter"],
                    "through_chapter": chapters[-1]["chapter"],
                    "mode": "range",
                },
            )
        skipped = 0
        for index, item in enumerate(chapters):
            await self.cancel(job["id"])
            parent = await self.store.plan(job["id"])
            if parent is None:
                raise IllustrationSourceChanged(
                    "Illustration range was invalidated. Request a fresh range."
                )
            chapter = item["chapter"]

            async def report(job_id, progress, *, stage=None):
                await self.progress(
                    job_id,
                    {
                        **progress,
                        "done": index,
                        "total": total,
                        "chapter": chapter,
                        "skipped": skipped,
                        "range_started": True,
                        # Range progress is visible before these chapters are read.
                        # Use generic phases, never future character names/scene titles.
                        "stage": f"Chapter {chapter:g}: {stage or 'Checking existing illustrations'}",
                    },
                    stage=f"Illustrating chapter {chapter:g} ({index + 1}/{total})",
                )

            await report(job["id"], {"stage": "Checking existing illustrations"})
            # Resume our own partial plan even if another complete batch is visible.
            if (
                not options.get("force")
                and await self.store.range_plan(job["id"], chapter) is None
            ):
                existing = [
                    row
                    for row in complete_scenes(
                        await self.current_rows(job["novel_id"], chapter)
                    )
                    if row["style"] == options["style"]
                    and current_style(options["style"], metadata(row))
                ]
                if existing:
                    skipped += 1
                    continue
            child = {
                **job,
                "options": {
                    "chapter": chapter,
                    "count": None,
                    "style": options["style"],
                    "source_hash": item["source_hash"],
                },
            }
            await self.execute_chapter(child, report)
        await self.cancel(job["id"])
        return {
            "done": total,
            "total": total,
            "skipped": skipped,
            "range_started": True,
            "stage": "Chapter illustrations ready",
        }
