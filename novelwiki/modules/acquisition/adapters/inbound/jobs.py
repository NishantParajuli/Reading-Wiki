from __future__ import annotations


async def execute_scrape_job(job: dict, context) -> dict:
    job_id = int(job["id"])
    novel_id = int(job["novel_id"])
    options = job.get("options") or {}
    credential_user_id = int(job["user_id"]) if job.get("user_id") is not None else None
    await context.bail_if_canceled(job_id)
    await context.update_job(job_id, stage="scraping")
    cancel = lambda: context.bail_if_canceled(job_id)
    if options.get("source_id") is not None:
        scraped = await context.scrape_source(
            int(options["source_id"]), force=bool(options.get("force")),
            max_chapters=options.get("max_chapters"), expected_novel_id=novel_id,
            cancel_check=cancel, credential_user_id=credential_user_id,
        )
    else:
        scraped = await context.scrape_novel(
            novel_id, force=bool(options.get("force")),
            max_chapters=options.get("max_chapters"), cancel_check=cancel,
            credential_user_id=credential_user_id,
        )
    await context.bail_if_canceled(job_id)
    return {"scraped": int(scraped)}
