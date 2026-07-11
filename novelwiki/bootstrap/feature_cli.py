"""Composition of feature application commands for CLI adapters."""
from __future__ import annotations


def build_codex_commands():
    from novelwiki.modules.codex.application.commands import CodexCommands
    from novelwiki.modules.codex.public import (
        chunk_all_chapters, embed_missing_chunks, extract_all_chapters, get_bm25_manager,
    )
    from novelwiki.bootstrap.cli_services import merge_codex_entities

    async def rebuild(novel_id):
        return await get_bm25_manager(novel_id).rebuild()

    return CodexCommands(
        chunk=chunk_all_chapters, embed=embed_missing_chunks,
        extract=extract_all_chapters, rebuild=rebuild, merge=merge_codex_entities,
    )


def build_translation_commands():
    from novelwiki.modules.translation.application.commands import TranslationCommands
    from novelwiki.modules.translation.adapters.outbound.runtime import (
        translate_range, seed_glossary_from_entities,
    )
    return TranslationCommands(translate_range, seed_glossary_from_entities)
