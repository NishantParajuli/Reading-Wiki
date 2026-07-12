"""Stable Acquisition import-commit compatibility entrypoint."""

from novelwiki.modules.acquisition.adapters.outbound.importer.commit import (
    _assign_global_numbers, _series_index, _volume_label,
)


def _runtime():
    from novelwiki.bootstrap.acquisition_runtime import build_acquisition_runtime
    return build_acquisition_runtime()


async def _resolve_target(*args, **kwargs):
    from novelwiki.bootstrap.acquisition_routes import bind_import_commit_apis
    from novelwiki.modules.acquisition.adapters.outbound.importer.commit import _resolve_target as run
    values = list(args)
    if values and not hasattr(values[0], "acquisition"):
        values[0] = bind_import_commit_apis(values[0])
    return await run(*values, **kwargs)


async def _preserve_replaced_content_version(*args, **kwargs):
    from novelwiki.bootstrap.acquisition_routes import bind_import_commit_apis
    from novelwiki.modules.acquisition.adapters.outbound.importer.commit import (
        _preserve_replaced_content_version as run,
    )
    values = list(args)
    if values:
        values[0] = bind_import_commit_apis(values[0]).reading
    return await run(*values, **kwargs)


async def commit_job(*args, **kwargs):
    from novelwiki.modules.acquisition.adapters.outbound.importer.commit import commit_job as run
    return await run(*args, runtime=_runtime(), **kwargs)


async def commit_series(*args, **kwargs):
    from novelwiki.modules.acquisition.adapters.outbound.importer.commit import commit_series as run
    return await run(*args, runtime=_runtime(), **kwargs)


async def _reserve_auto_codex(*args, **kwargs):
    from novelwiki.modules.acquisition.adapters.outbound.importer.commit import _reserve_auto_codex as run
    return await run(*args, runtime=_runtime(), **kwargs)


async def _schedule_codex(*args, **kwargs):
    from novelwiki.modules.acquisition.adapters.outbound.importer.commit import _schedule_codex as run
    return await run(*args, runtime=_runtime(), **kwargs)
