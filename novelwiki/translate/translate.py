"""Stable Translation compatibility entrypoint."""

from novelwiki.modules.translation.adapters.outbound.runtime import (
    SourceChangedError, _format_glossary, _parse_translation, source_sha256,
)
from novelwiki.modules.ai_execution.adapters.outbound.providers import (
    call_chat_completion,
)


async def _run(name, *args, **kwargs):
    from novelwiki.bootstrap.translation import build_translation_execution_runtime
    from novelwiki.modules.translation.adapters.outbound import runtime as implementation
    runtime = kwargs.pop("runtime", None) or build_translation_execution_runtime()
    runtime.ai.call_chat_completion = call_chat_completion
    return await getattr(implementation, name)(*args, runtime=runtime, **kwargs)


async def stage_translation_batch(*args, **kwargs):
    return await _run("stage_translation_batch", *args, **kwargs)


async def reset_staged_translations(*args, **kwargs):
    return await _run("reset_staged_translations", *args, **kwargs)


async def commit_translation(*args, **kwargs):
    return await _run("commit_translation", *args, **kwargs)


async def translate_chapter(*args, **kwargs):
    return await _run("translate_chapter", *args, **kwargs)


async def translate_raw_text(*args, **kwargs):
    return await _run("translate_raw_text", *args, **kwargs)


async def prefetch_translations(*args, **kwargs):
    return await _run("prefetch_translations", *args, **kwargs)


async def translate_range(*args, **kwargs):
    return await _run("translate_range", *args, **kwargs)


async def seed_glossary_from_entities(*args, **kwargs):
    return await _run("seed_glossary_from_entities", *args, **kwargs)
