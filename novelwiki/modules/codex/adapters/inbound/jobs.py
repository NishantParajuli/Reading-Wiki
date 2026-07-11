from __future__ import annotations


async def execute_codex_job(job: dict, context) -> dict:
    job_id, novel_id = int(job["id"]), int(job["novel_id"])
    options = job.get("options") or {}
    force = bool(options.get("force"))
    start, end = options.get("from_chapter"), options.get("to_chapter")
    cancel = lambda: context.bail_if_canceled(job_id)
    stages = (
        ("chunking", context.chunk_all_chapters, {"force": force, "from_chapter": start, "to_chapter": end}),
        ("embedding", context.embed_missing_chunks, {"from_chapter": start, "to_chapter": end}),
        ("extracting", context.extract_all_chapters, {"force": force, "from_chapter": start, "to_chapter": end}),
    )
    for index, (stage, operation, kwargs) in enumerate(stages, 1):
        await context.set_progress(
            job_id, {"step": index, "steps": 4, "stage": stage}, stage=stage
        )
        await operation(novel_id, cancel_check=cancel, **kwargs)
        await context.bail_if_canceled(job_id)
    await context.set_progress(
        job_id, {"step": 4, "steps": 4, "stage": "indexing"}, stage="indexing"
    )
    await context.rebuild_bm25(novel_id)
    return {"step": 4, "steps": 4}


async def execute_agy_codex_job(job: dict, preflight, context) -> dict:
    options = job.get("options") or {}
    job_id, novel_id = int(job["id"]), int(job["novel_id"])
    cancel = lambda: context.bail_if_canceled(job_id)
    await cancel()
    await context.set_progress(job_id, {"step": 1, "steps": 4, "stage": "chunking"}, stage="chunking")
    await context.chunk_all_chapters(
        novel_id, force=bool(options.get("force")),
        from_chapter=options.get("from_chapter"), to_chapter=options.get("to_chapter"),
        cancel_check=cancel,
    )
    await cancel()
    await context.set_progress(job_id, {"step": 2, "steps": 4, "stage": "embedding"}, stage="embedding")
    await context.embed_missing_chunks(
        novel_id, from_chapter=options.get("from_chapter"),
        to_chapter=options.get("to_chapter"), cancel_check=cancel,
    )
    await cancel()
    extracted = await context.execute_codex_job(job, preflight)
    await cancel()
    await context.set_progress(job_id, {"step": 4, "steps": 4, **extracted}, stage="indexing")
    await context.rebuild_bm25(novel_id)
    return {"step": 4, "steps": 4, **extracted}
