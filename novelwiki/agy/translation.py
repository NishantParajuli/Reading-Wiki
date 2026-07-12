"""Stable Translation AGY compatibility entrypoint."""

from novelwiki.modules.translation.adapters.outbound.agy import (
    _batch, _chapter_ref, _validate_quality,
)


def validate_translation_output(*args, **kwargs):
    from novelwiki.bootstrap.translation import build_translation_execution_runtime
    from novelwiki.modules.translation.adapters.outbound.agy import validate_translation_output as run
    return run(*args, runtime=build_translation_execution_runtime(), **kwargs)


async def execute_translation_job(*args, **kwargs):
    from novelwiki.bootstrap.translation import build_translation_execution_runtime
    from novelwiki.modules.translation.adapters.outbound.agy import execute_translation_job as run
    return await run(
        *args, runtime=build_translation_execution_runtime(), **kwargs
    )
