"""Stable Codex extraction compatibility entrypoint."""

from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
    EXTRACTION_KEYS, chapter_source_sha256,
)


async def commit_extraction_proposal(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
        commit_extraction_proposal as run,
    )
    runtime = build_codex_runtime()
    kwargs.pop("entity_resolver", None)
    return await run(
        *args, uow_factory=runtime.extraction_uow_factory, **kwargs
    )


async def extract_knowledge_for_chapter(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
        extract_knowledge_for_chapter as run,
    )
    runtime = kwargs.pop("runtime", None) or build_codex_runtime()
    return await run(*args, runtime=runtime, **kwargs)


async def extract_all_chapters(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.ingest.extract import extract_all_chapters as run
    runtime = kwargs.pop("runtime", None) or build_codex_runtime()
    return await run(*args, runtime=runtime, **kwargs)
