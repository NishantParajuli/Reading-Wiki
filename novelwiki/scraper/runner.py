"""Stable Acquisition scraper compatibility entrypoint."""


async def _run(name, *args, **kwargs):
    from novelwiki.bootstrap.acquisition_runtime import build_acquisition_runtime
    from novelwiki.modules.acquisition.adapters.outbound.scraper import runner
    runtime = kwargs.pop("runtime", None) or build_acquisition_runtime()
    return await getattr(runner, name)(
        *args, runtime=runtime, **kwargs
    )


async def scrape_source(*args, **kwargs):
    return await _run("scrape_source", *args, **kwargs)


async def scrape_novel(*args, **kwargs):
    kwargs.setdefault("scrape_source_operation", scrape_source)
    return await _run("scrape_novel", *args, **kwargs)


async def set_source_offset(*args, **kwargs):
    return await _run("set_source_offset", *args, **kwargs)


async def _persist_chapter(*args, **kwargs):
    return await _run("_persist_chapter", *args, **kwargs)


async def _resume_url(*args, **kwargs):
    return await _run("_resume_url", *args, **kwargs)
