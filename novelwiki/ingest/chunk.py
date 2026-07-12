"""Stable Codex chunking compatibility entrypoint."""

from novelwiki.modules.codex.adapters.outbound.ingest.chunk import (
    chunk_chapter_text, count_tokens, get_encoder, split_by_sentences,
)


async def chunk_chapter(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.ingest.chunk import chunk_chapter as run
    runtime = kwargs.pop("runtime", None) or build_codex_runtime()
    return await run(*args, runtime=runtime, **kwargs)


async def chunk_all_chapters(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.ingest.chunk import chunk_all_chapters as run
    runtime = kwargs.pop("runtime", None) or build_codex_runtime()
    return await run(*args, runtime=runtime, **kwargs)
