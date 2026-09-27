from __future__ import annotations

from novelwiki.kernel.errors import Conflict
from ..domain.illustrations import (
    ContextDecision,
    CONTEXT_INSTRUCTIONS,
    IllustrationPlan,
    PLANNER_INSTRUCTIONS,
    STYLES,
    placement_metadata,
    render_prompt,
    source_hash,
    validate_plan,
)
from .illustrations import IllustrationSourceChanged, metadata


class IllustrationWorker:
    def __init__(self, *, store, snapshot, renderer, progress, cancel, preceding=None):
        self.store, self.snapshot, self.renderer = store, snapshot, renderer
        self.progress, self.cancel = progress, cancel
        self.preceding = preceding

    async def execute(self, job):
        job_id, novel_id = job["id"], job["novel_id"]
        options = job["options"]
        chapter, style, count = (
            float(options["chapter"]),
            options["style"],
            options.get("count"),
        )
        if count == "auto":
            count = None
        if style not in STYLES or (
            count is not None and (type(count) is not int or count not in (1, 2, 3))
        ):
            raise ValueError("Invalid illustration request")
        plan_persisted = False
        context_sources = []

        def provenance(context):
            # Old saved plans predate context hashes and remain resumable.
            return [
                {"chapter": float(row["chapter"]), "source_hash": row["source_hash"]}
                for row in context.get("previous_chapters", [])
                if row.get("source_hash")
            ]

        async def current():
            await self.cancel(job_id)
            snapshot = await self.snapshot(novel_id, chapter)
            if (
                not snapshot
                or not snapshot.get("content")
                or source_hash(snapshot) != options["source_hash"]
            ):
                raise IllustrationSourceChanged(
                    "Chapter changed while illustrations were being prepared. Request a fresh set."
                )
            for origin in context_sources:
                previous = await self.snapshot(novel_id, origin["chapter"])
                if (
                    not previous
                    or not previous.get("content")
                    or source_hash(previous) != origin["source_hash"]
                ):
                    raise IllustrationSourceChanged(
                        "A preceding chapter used for art context changed. Request a fresh set."
                    )
            if plan_persisted and not await self.store.plan(job_id):
                raise IllustrationSourceChanged(
                    "Illustration context was invalidated. Request a fresh set."
                )
            return snapshot

        async def reference(row):
            if (
                not row
                or row["kind"] != "reference"
                or row["style"] != style
                or int(row["novel_id"]) != novel_id
                or float(row["chapter"]) > chapter
            ):
                raise IllustrationSourceChanged(
                    "A required character sheet was removed or changed. Request a fresh set."
                )
            source = await self.snapshot(novel_id, float(row["chapter"]))
            if (
                not source
                or not source.get("content")
                or source_hash(source) != row["source_hash"]
            ):
                raise IllustrationSourceChanged(
                    "A character sheet source changed. Request a fresh illustration set."
                )
            for origin in metadata(row).get("sources", []):
                original = await self.snapshot(novel_id, float(origin["chapter"]))
                if (
                    not original
                    or not original.get("content")
                    or source_hash(original) != origin["source_hash"]
                ):
                    raise IllustrationSourceChanged(
                        "A character name or original sheet source changed. Request a fresh illustration set."
                    )
            return row

        snapshot = await current()
        saved = await self.store.plan(job_id)
        if not saved:
            await self.progress(
                job_id,
                {"stage": "Checking story context", "step": 0, "steps": 1},
                stage="Planning illustrations",
            )
            decision = ContextDecision.model_validate(
                await self.renderer.plan(
                    CONTEXT_INSTRUCTIONS,
                    {
                        "chapter": chapter,
                        "title": snapshot["title"],
                        "text": snapshot["content"],
                        "length": {
                            "characters": len(snapshot["content"]),
                            "words": len(snapshot["content"].split()),
                        },
                    },
                    ContextDecision.model_json_schema(),
                )
            )
            if bool(decision.previous_chapters) != bool(decision.max_chars):
                raise ValueError(
                    "Illustration context count and budget must both be zero or positive"
                )
            await current()
            knowledge = {"previous_chapters": []}
            if decision.previous_chapters and self.preceding:
                preceding = await self.preceding(
                    novel_id, chapter, decision.previous_chapters, decision.max_chars
                )
                knowledge = await self.store.context(
                    novel_id, chapter, preceding=preceding, max_chars=decision.max_chars
                )
            context_sources = provenance(knowledge)
            await current()
            existing = {}
            for row in await self.store.references(
                novel_id, chapter, style, snapshot["content"]
            ):
                if (
                    row["kind"] != "reference"
                    or row["style"] != style
                    or row["character_key"] in existing
                ):
                    continue
                try:
                    existing[row["character_key"]] = await reference(row)
                except Conflict:
                    continue
            await self.progress(
                job_id,
                {"stage": "Choosing scenes", "step": 0, "steps": count or 1},
                stage="Planning illustrations",
            )
            data = {
                "chapter": chapter,
                "title": snapshot["title"],
                "text": snapshot["content"],
                "scene_count": count,
                "style": STYLES[style],
                "knowledge": knowledge,
                "context_decision": decision.model_dump(),
                "existing_characters": [
                    {
                        "key": key,
                        "name": row["title"],
                        "aliases": metadata(row).get("aliases", []),
                        "canon": metadata(row).get("canon", ""),
                        "design_notes": metadata(row).get("design_notes", ""),
                        "prompt": metadata(row).get("prompt", ""),
                    }
                    for key, row in existing.items()
                ],
            }
            plan = IllustrationPlan.model_validate(
                await self.renderer.plan(
                    PLANNER_INSTRUCTIONS,
                    data,
                    IllustrationPlan.model_json_schema(),
                )
            )
            await current()
            validate_plan(
                plan,
                snapshot["content"],
                count,
                set(existing),
                existing_names={key: row["title"] for key, row in existing.items()},
            )
            used = {key for scene in plan.scenes for key in scene.characters}
            saved = await self.store.save_plan(
                job_id,
                {
                    "novel_id": novel_id,
                    "chapter": chapter,
                    "source_hash": options["source_hash"],
                    "plan": plan.model_dump(),
                    "context_decision": decision.model_dump(),
                    "context": knowledge,
                    "references": {
                        key: str(row["id"])
                        for key, row in existing.items()
                        if key in used
                        or key in {update.key for update in plan.name_updates}
                    },
                },
            )
        plan_persisted = True
        context_sources = provenance(saved.get("context", {}))
        await current()
        # Always use the persisted winner, including when two recovered attempts race.
        plan = IllustrationPlan.model_validate(saved["plan"])
        existing = {
            key: await reference(await self.store.get(novel_id, art_id, images=False))
            for key, art_id in saved["references"].items()
        }
        validate_plan(
            plan,
            snapshot["content"],
            count,
            set(existing),
            existing_names={key: row["title"] for key, row in existing.items()},
        )
        count = len(plan.scenes)
        completed = {row["slot"]: row for row in await self.store.for_job(job_id)}
        used = {key for scene in plan.scenes for key in scene.characters}
        for update in plan.name_updates:
            await current()
            prior = existing[update.key]
            previous = metadata(prior)
            aliases = list(
                dict.fromkeys(
                    [*previous.get("aliases", []), prior["title"], *update.aliases]
                )
            )
            if update.name == prior["title"] and set(aliases) <= set(
                previous.get("aliases", [])
            ) | {prior["title"]}:
                continue
            slot = "name:" + update.key
            if slot in completed:
                existing[update.key] = await reference(completed[slot])
                continue
            prior = await reference(await self.store.get(novel_id, prior["id"]))
            sources = [
                *previous.get("sources", []),
                *context_sources,
                {
                    "chapter": float(prior["chapter"]),
                    "source_hash": prior["source_hash"],
                },
            ]
            # A name revision reuses the original pixels. Keep chapter-scoped provenance
            # so a later identity reveal never rewrites an earlier chapter's sheet.
            existing[update.key] = await self.store.save(
                novel_id=novel_id,
                chapter=chapter,
                kind="reference",
                key=update.key,
                title=update.name,
                caption=prior["caption"],
                style=style,
                source_hash=options["source_hash"],
                metadata={
                    **previous,
                    "aliases": aliases,
                    "sources": sources,
                    "name_evidence": update.evidence,
                    "batch": job_id,
                },
                image=prior["image"],
                job_id=job_id,
                slot=slot,
            )
        for design in plan.characters:
            if design.key in existing or design.key not in used:
                continue
            slot = "reference:" + design.key
            if slot in completed:
                existing[design.key] = await reference(completed[slot])
                continue
            await current()
            await self.progress(
                job_id,
                {"stage": f"Designing {design.name}"},
                stage="Creating character sheets",
            )
            prompt = render_prompt(design.prompt, style, [], reference=True)
            image = await self.renderer.image(prompt, [])
            await current()
            existing[design.key] = await self.store.save(
                novel_id=novel_id,
                chapter=chapter,
                kind="reference",
                key=design.key,
                title=design.name,
                caption="Character reference sheet",
                style=style,
                source_hash=options["source_hash"],
                metadata={
                    "prompt": prompt,
                    "canon": design.canon,
                    "sources": context_sources,
                    "design_notes": design.design_notes,
                    "model": "gpt-6-luna",
                    "effort": "max",
                    "batch": job_id,
                },
                image=image,
                job_id=job_id,
                slot=slot,
            )
        for index, scene in enumerate(plan.scenes):
            await current()
            slot = f"scene:{index}"
            refs = [
                await reference(
                    await self.store.get(novel_id, existing[key]["id"], images=False)
                )
                for key in scene.characters
            ]
            if slot in completed:
                if metadata(completed[slot]).get("references") != [
                    str(row["id"]) for row in refs
                ]:
                    raise IllustrationSourceChanged(
                        "A saved illustration uses different character sheets. Request a fresh set."
                    )
                continue
            await self.progress(
                job_id,
                {
                    "stage": f"Rendering image {index + 1} of {count}",
                    "step": index,
                    "steps": count,
                },
                stage="Painting chapter scenes",
            )
            refs = [
                await reference(await self.store.get(novel_id, row["id"]))
                for row in refs
            ]
            prompt = render_prompt(scene.prompt, style, [row["title"] for row in refs])
            image = await self.renderer.image(prompt, [row["image"] for row in refs])
            await current()
            for row in refs:
                await reference(row)
            await self.store.save(
                novel_id=novel_id,
                chapter=chapter,
                kind="scene",
                key=None,
                title=scene.title,
                caption=scene.caption,
                style=style,
                source_hash=options["source_hash"],
                metadata={
                    "prompt": prompt,
                    "evidence": scene.evidence,
                    "sources": context_sources,
                    "placement": placement_metadata(scene, snapshot["content"]),
                    "references": [str(row["id"]) for row in refs],
                    "batch": job_id,
                    "index": index,
                    "count": count,
                    "model": "gpt-6-luna",
                    "effort": "max",
                },
                image=image,
                job_id=job_id,
                slot=slot,
            )
        await current()
        return {
            "stage": "Illustrations ready",
            "step": count,
            "steps": count,
            "images": count,
        }
