"""Stable Codex embedding compatibility entrypoint."""

from novelwiki.modules.ai_execution.adapters.outbound.providers import (
    get_embeddings_batch,
)


async def embed_missing_chunks(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.ingest.embed import embed_missing_chunks as run
    runtime = kwargs.pop("runtime", None) or build_codex_runtime()
    runtime.ai.get_embeddings_batch = get_embeddings_batch
    return await run(*args, runtime=runtime, **kwargs)
