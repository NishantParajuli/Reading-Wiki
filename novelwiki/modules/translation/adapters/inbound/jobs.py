from __future__ import annotations


async def execute_translation_job(job: dict, context) -> dict:
    job_id, novel_id = int(job["id"]), int(job["novel_id"])
    options = job.get("options") or {}
    force = bool(options.get("force"))
    user = await context.load_user(job.get("user_id"))
    if user is None or not context.spend_allowed(user):
        raise RuntimeError("Verify your email before running a translation batch.")
    if options.get("seed_from_codex"):
        await context.update_job(job_id, stage="seeding glossary")
        await context.seed_glossary(novel_id)
    chapters = await context.pending_translations(
        novel_id, options.get("from_chapter"), options.get("to_chapter"), force
    )
    total = len(chapters)
    done = failed = 0
    await context.set_progress(job_id, {"done": 0, "total": total}, stage="translating")
    for number in chapters:
        await context.bail_if_canceled(job_id)
        result = await context.translate_chapter(
            novel_id, number, force=force, meter_user=user
        )
        status = result.get("status")
        if status == "quota_exceeded":
            progress = {"done": done, "failed": failed, "total": total,
                        "stopped_reason": "quota"}
            await context.set_progress(job_id, progress)
            return progress
        done += status == "done"
        failed += status == "failed"
        await context.set_progress(
            job_id, {"done": done, "failed": failed, "total": total,
                     "current_chapter": number}
        )
    return {"done": done, "failed": failed, "total": total}
