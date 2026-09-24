from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novelwiki.modules.acquisition.adapters.outbound.scraper import runner
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import ChapterData, ScrapeError


def chapter(number, content="Synthetic prose."):
    return ChapterData(number=number, title="Synthetic chapter", content=content,
                       url=f"https://readhive.org/novel/1/{number}")


def setup_run(monkeypatch, chapters, *, resume=None, force_writes=None, config=None, offset=0):
    source = dict(id=1, novel_id=2, adapter="readhive", start_url="https://readhive.org/novel/1/1",
                  config=config or {}, language="en", is_raw=False, chapter_offset=offset)
    connection = SimpleNamespace(fetchrow=AsyncMock(return_value=source), execute=AsyncMock())

    @asynccontextmanager
    async def acquire():
        yield connection

    pool = SimpleNamespace(acquire=acquire)
    monkeypatch.setattr(runner, "get_db_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(runner.settings, "SCRAPER_DELAY", 0)
    contexts = []

    class Adapter:
        allowed_hosts = ["readhive.org"]

        async def crawl(self, ctx):
            contexts.append(ctx)
            for value in chapters[:ctx.max_chapters]:
                yield value

    monkeypatch.setattr(runner, "get_adapter", lambda _: Adapter())
    runtime = SimpleNamespace(resume_url=AsyncMock(return_value=resume),
                              upsert_ingested_chapter=AsyncMock(side_effect=force_writes, return_value=True))
    return runtime, connection, contexts


@pytest.mark.asyncio
async def test_resuming_with_limit_one_advances_beyond_saved_checkpoint(monkeypatch):
    runtime, connection, contexts = setup_run(
        monkeypatch, [chapter(10), chapter(11), chapter(12)],
        resume=chapter(10).url, force_writes=[False, True],
    )
    assert await runner.scrape_source(1, max_chapters=1, runtime=runtime) == 1
    assert contexts[0].max_chapters == 2
    assert [call.args[1] for call in runtime.upsert_ingested_chapter.await_args_list] == [10, 11]
    connection.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_force_starts_at_source_and_honors_write_limit(monkeypatch):
    runtime, _, contexts = setup_run(monkeypatch, [chapter(1), chapter(2)], resume=chapter(10).url)
    assert await runner.scrape_source(1, force=True, max_chapters=1, runtime=runtime) == 1
    runtime.resume_url.assert_not_awaited()
    assert contexts[0].start_url.endswith("/1") and contexts[0].max_chapters == 1
    assert runtime.upsert_ingested_chapter.await_args.args[3] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,resume", [
    ([chapter(None)], chapter(10).url),
    ([chapter(float("nan"))], None),
    ([chapter(float("inf"))], None),
    ([chapter(1, "   ")], None),
    ([chapter(2), chapter(2)], None),
    ([chapter(2), chapter(1)], None),
])
async def test_invalid_chapters_fail_without_marking_source_success(monkeypatch, rows, resume):
    runtime, connection, _ = setup_run(monkeypatch, rows, resume=resume)
    with pytest.raises(ScrapeError):
        await runner.scrape_source(1, runtime=runtime)
    assert runtime.upsert_ingested_chapter.await_count == len(rows) - 1
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_unnumbered_chapters_follow_last_known_number(monkeypatch):
    runtime, _, _ = setup_run(monkeypatch, [chapter(9), chapter(None)], offset=100)
    assert await runner.scrape_source(1, runtime=runtime) == 2
    assert [call.args[1] for call in runtime.upsert_ingested_chapter.await_args_list] == [109, 110]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,offset", [("broken-json", 0), ([1], 0), ({}, float("inf"))])
async def test_invalid_source_settings_fail_before_crawling(monkeypatch, config, offset):
    runtime, connection, contexts = setup_run(monkeypatch, [], config=config, offset=offset)
    with pytest.raises(ScrapeError):
        await runner.scrape_source(1, runtime=runtime)
    assert contexts == []
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_does_not_record_success(monkeypatch):
    runtime, connection, _ = setup_run(monkeypatch, [chapter(1)])
    cancel = AsyncMock(side_effect=RuntimeError("cancelled"))
    with pytest.raises(RuntimeError, match="cancelled"):
        await runner.scrape_source(1, cancel_check=cancel, runtime=runtime)
    runtime.upsert_ingested_chapter.assert_not_awaited()
    connection.execute.assert_not_awaited()
