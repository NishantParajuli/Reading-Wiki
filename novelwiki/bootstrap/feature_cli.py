"""Composition of feature application commands for CLI adapters."""
from __future__ import annotations


def build_codex_commands():
    from functools import partial
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.application.commands import CodexCommands
    from novelwiki.modules.codex.adapters.outbound.ingest.chunk import chunk_all_chapters
    from novelwiki.modules.codex.adapters.outbound.ingest.embed import embed_missing_chunks
    from novelwiki.modules.codex.adapters.outbound.ingest.extract import extract_all_chapters
    from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import (
        get_bm25_manager,
    )
    from novelwiki.bootstrap.cli_services import merge_codex_entities

    async def rebuild(novel_id):
        return await get_bm25_manager(novel_id).rebuild()

    runtime = build_codex_runtime()
    return CodexCommands(
        chunk=partial(chunk_all_chapters, runtime=runtime),
        embed=partial(embed_missing_chunks, runtime=runtime),
        extract=partial(extract_all_chapters, runtime=runtime),
        rebuild=rebuild, merge=merge_codex_entities,
    )


def build_translation_commands():
    from functools import partial
    from novelwiki.bootstrap.translation import build_translation_execution_runtime
    from novelwiki.modules.translation.application.commands import TranslationCommands
    from novelwiki.modules.translation.adapters.outbound.runtime import (
        translate_range, seed_glossary_from_entities,
    )
    runtime = build_translation_execution_runtime()
    return TranslationCommands(
        partial(translate_range, runtime=runtime),
        partial(seed_glossary_from_entities, runtime=runtime),
    )
