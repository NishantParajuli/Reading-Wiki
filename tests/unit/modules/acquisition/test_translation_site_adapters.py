"""Synthetic reader fixtures: no copied chapters or live network requests."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novelwiki.modules.acquisition.adapters.outbound.scraper.base import PremiumReached
from novelwiki.modules.acquisition.adapters.outbound.scraper.translation_sites import (
    AzureChroniclesAdapter,
    DreamyTranslationsAdapter,
    PenguinSquadAdapter,
)


ADAPTERS = [DreamyTranslationsAdapter, PenguinSquadAdapter, AzureChroniclesAdapter]


def chapter_url(adapter, number):
    suffix = f"chapter/{number}" if adapter.name == "dreamy-translations" else f"chapter-{number}"
    if adapter.name == "penguin-squad":
        suffix += "-the-99-doors"
    return f"https://{adapter.domain}/{adapter.novel_prefix}/synthetic/{suffix}"


def flight(props, *, split=False):
    payload = 'f:["$","$L3",null,' + json.dumps(props) + ']\n'
    chunks = [payload[:17], payload[17:]] if split else [payload]
    return "".join(f"<script>self.__next_f.push({json.dumps([1, chunk])});</script>" for chunk in chunks)


def page(adapter, number=1, *, next_number=None, locked=False, body=None):
    body = body if body is not None else "<p>The <em>red</em> door.</p><p>A second line.<br>After a break.</p>"
    next_url = chapter_url(adapter, next_number) if next_number is not None else ""
    if adapter.name == "dreamy-translations":
        reader = f'<div class="group/title"><button>The 99 Doors</button></div><article class="chapter-content">{body}</article>'
        nav = f'<a href="{next_url}"><span>Next</span><span>The next door</span></a>' if next_url else ""
        data = flight({"slug": "synthetic", "chapter": {"index": number}, "hasAccess": not locked}, split=True)
    elif adapter.name == "penguin-squad":
        reader = f'<h1>The 99 Doors</h1><div class="reader-content">{body}</div>'
        nav = f'<a aria-label="Next chapter ({next_number})" href="{next_url}"></a>' if next_url else ""
        data = '<span data-slot="badge">Premium</span><h2>Unlock this chapter free</h2>' if locked else ""
    else:
        reader = f'<div id="ac-r-body"><h1 class="ac-r-chapter-name">Chapter {number}</h1><p>Chapter {number}</p>{body}</div>'
        nav = f'<a title="Next" href="{next_url}"></a>' if next_url else ""
        data = '<script id="ac-chapter-reader-js-before">window.acReaderData = ' + json.dumps({"canRead": not locked}) + ';</script>'
    return f'<main>{reader}{nav}</main>{data}<footer>Account and unrelated comments</footer>'


def context(url, pages, *, maximum=None, stop=True):
    return SimpleNamespace(
        start_url=url,
        fetch_text=AsyncMock(side_effect=lambda url: pages.get(url)),
        max_chapters=maximum,
        stop_on_premium=stop,
    )


async def collect(adapter, ctx):
    return [chapter async for chapter in adapter.crawl(ctx)]


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
async def test_novel_start_orders_chapters_and_preserves_reader_text(adapter_type):
    adapter = adapter_type()
    novel = f"https://{adapter.domain}/{adapter.novel_prefix}/synthetic"
    first, second = chapter_url(adapter, 0), chapter_url(adapter, 0.5)
    toc = (
        f'<a href="{chapter_url(adapter, 8)}">Latest chapter</a>'
        f'<a href="{first.replace("synthetic", "other")}">Other novel</a>'
        f'<a href="{second}">Chapter 0.5</a><a href="{first}">Chapter 0</a>'
    )
    ctx = context(novel, {novel: toc, first: page(adapter, 0, next_number=0.5), second: page(adapter, 0.5)})
    result = await collect(adapter, ctx)
    assert [chapter.number for chapter in result] == [0, 0.5]
    assert [chapter.url for chapter in result] == [first, second]
    assert all(chapter.content == "The red door.\n\nA second line.\n\nAfter a break." for chapter in result)
    assert result[0].title == ("Chapter 0" if adapter.name == "azurechronicles" else "The 99 Doors")
    assert ctx.fetch_text.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
async def test_read_link_reaches_first_chapter_despite_partial_toc(adapter_type):
    adapter = adapter_type()
    novel = f"https://{adapter.domain}/{adapter.novel_prefix}/synthetic/"
    first = chapter_url(adapter, 1)
    ctx = context(novel, {novel: f'<a href="{chapter_url(adapter, 90)}">Chapter 90</a><a href="{first}">Start Reading</a>', first: page(adapter)})
    assert [chapter.number for chapter in await collect(adapter, ctx)] == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
async def test_public_premium_metadata_stops_before_preview_can_be_saved(adapter_type):
    adapter = adapter_type()
    start = chapter_url(adapter, 1)
    ctx = context(start, {start: page(adapter, locked=True, next_number=2)})
    with pytest.raises(PremiumReached) as exc:
        await collect(adapter, ctx)
    assert exc.value.number == 1
    assert ctx.fetch_text.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
async def test_skip_premium_only_follows_existing_public_next_link(adapter_type):
    adapter = adapter_type()
    first, second = chapter_url(adapter, 1), chapter_url(adapter, 2)
    ctx = context(first, {first: page(adapter, locked=True, next_number=2), second: page(adapter, 2)}, stop=False)
    assert [chapter.number for chapter in await collect(adapter, ctx)] == [2]
    ctx = context(first, {first: page(adapter, locked=True)}, stop=False)
    assert await collect(adapter, ctx) == []
    assert ctx.fetch_text.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
@pytest.mark.parametrize("maximum", [0, 1])
async def test_maximum_does_not_fetch_unneeded_chapters(adapter_type, maximum):
    adapter = adapter_type()
    first = chapter_url(adapter, 1)
    ctx = context(first, {first: page(adapter, next_number=2)}, maximum=maximum)
    assert len(await collect(adapter, ctx)) == maximum
    assert ctx.fetch_text.await_count == maximum


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
async def test_navigation_cannot_loop_leave_series_or_follow_external_site(adapter_type):
    adapter = adapter_type()
    first = chapter_url(adapter, 1)
    bad_links = [first, chapter_url(adapter, 0), chapter_url(adapter, 2).replace("synthetic", "other"), chapter_url(adapter, 2).replace(adapter.domain, "attacker.invalid")]
    html = page(adapter) + "".join(f'<a rel="next" href="{url}">Next</a>' for url in bad_links)
    ctx = context(first, {first: html})
    assert len(await collect(adapter, ctx)) == 1
    assert ctx.fetch_text.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
@pytest.mark.parametrize("html", [None, "<main>Temporary outage</main>"])
async def test_failed_fetch_and_missing_reader_are_errors_not_premium(adapter_type, html):
    adapter = adapter_type()
    first = chapter_url(adapter, 1)
    ctx = context(first, {first: html})
    with pytest.raises(RuntimeError if html is None else ValueError):
        await collect(adapter, ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_type", ADAPTERS)
async def test_invalid_start_url_fails_before_fetch(adapter_type):
    adapter = adapter_type()
    for url in [f"https://{adapter.domain}/", chapter_url(adapter, 1).replace(adapter.domain, "attacker.invalid")]:
        ctx = context(url, {})
        with pytest.raises(ValueError):
            await collect(adapter, ctx)
        ctx.fetch_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_dreamy_access_flag_cannot_lock_a_free_chapter():
    adapter = DreamyTranslationsAdapter()
    first = chapter_url(adapter, 1)
    html = page(adapter) + flight({"slug": "other", "chapter": {"index": 1}, "hasAccess": False})
    assert len(await collect(adapter, context(first, {first: html}))) == 1


@pytest.mark.asyncio
async def test_azure_hidden_unlock_dialog_is_not_a_paywall():
    adapter = AzureChroniclesAdapter()
    first = chapter_url(adapter, 1)
    html = page(adapter) + '<div id="acl-overlay" aria-hidden="true">This chapter is locked. Unlock it.</div>'
    assert len(await collect(adapter, context(first, {first: html}))) == 1
