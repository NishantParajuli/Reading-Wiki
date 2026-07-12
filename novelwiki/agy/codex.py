"""Stable Codex AGY compatibility entrypoint."""

from novelwiki.modules.codex.adapters.outbound.agy import (
    ENTITY_TYPES, _claim_refs, _walk_strings,
)


def validate_extraction_output(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.agy import validate_extraction_output as run
    return run(*args, runtime=build_codex_runtime(), **kwargs)


async def execute_codex_job(*args, **kwargs):
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    from novelwiki.modules.codex.adapters.outbound.agy import execute_codex_job as run
    return await run(*args, runtime=build_codex_runtime(), **kwargs)
