from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from selectolax.parser import HTMLParser

from novelwiki.modules.acquisition.adapters.outbound.scraper import adapters
from novelwiki.modules.acquisition.adapters.outbound.scraper import base
from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import FetchHTTPError


class Pages:
    def __init__(self, pages, start, **kwargs):
        self.pages = pages
        self.start_url = start
        self.max_chapters = kwargs.get("max_chapters")
        self.stop_on_premium = kwargs.get("stop_on_premium", True)
        self.config = {}
        self.calls = []

    async def fetch_text(self, url):
        self.calls.append(url)
        assert len(self.calls) <= len(self.pages) + 1, "navigation did not advance"
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value

    async def fetch_json(self, url, **kwargs):
        return await self.fetch_text(url)

    async def fetch_bytes(self, url, **kwargs):
        return await self.fetch_text(url)


async def crawl(adapter, context):
    return [chapter async for chapter in adapter.crawl(context)]


def readhive(text, next_href=None):
    nav = f'<nav><a href="{next_href}">Next</a></nav>' if next_href else ""
    return f'<h1><span></span><strong>Chapter 1</strong></h1><div class="prose"><p>{text}</p>{nav}</div>'


@pytest.mark.asyncio
async def test_readhive_preserves_inline_spacing_short_text_and_nested_navigation():
    first, second = "https://readhive.org/series/1/1", "https://readhive.org/series/1/2"
    context = Pages({first: readhive('<span>Wind </span><em>and</em> <b>rain.</b><br>Then dawn.', second),
                     second: readhive("The end.")}, first, max_chapters=2)
    rows = await crawl(adapters.ReadhiveAdapter(), context)
    assert rows[0].title == "Chapter 1"
    assert rows[0].content == "Wind and rain.\nThen dawn."
    assert rows[1].content == "The end."
    assert context.calls == [first, second]


@pytest.mark.asyncio
async def test_crawl_rejects_navigation_cycle_before_refetching():
    url = "https://readhive.org/series/1/1"
    context = Pages({url: readhive("Opening paragraph.", url + "#chapter")}, url)
    with pytest.raises(base.ScrapeError, match="already visited"):
        await crawl(adapters.ReadhiveAdapter(), context)
    assert context.calls == [url]


@pytest.mark.asyncio
async def test_missing_content_is_failure_not_premium_or_success():
    url = "https://readhive.org/series/1/1"
    with pytest.raises(base.ScrapeError, match="no chapter content"):
        await crawl(adapters.ReadhiveAdapter(), Pages({url: '<title>Just a moment...</title>'}, url))


@pytest.mark.asyncio
async def test_explicit_paywall_stops_without_importing_prompt():
    url = "https://readhive.org/series/1/1"
    html = '<h1>Chapter 1</h1><div class="prose paywall">Unlock this chapter to read.</div>'
    with pytest.raises(base.PremiumReached):
        await crawl(adapters.ReadhiveAdapter(), Pages({url: html}, url))


@pytest.mark.asyncio
async def test_story_paywall_phrase_does_not_turn_prose_into_premium():
    url = "https://readhive.org/series/1/1"
    rows = await crawl(adapters.ReadhiveAdapter(), Pages({url: readhive('She joked, "Subscribe to read the ending."')}, url, max_chapters=1))
    assert "Subscribe" in rows[0].content


@pytest.mark.asyncio
async def test_only_predicted_404_is_successful_end_of_book():
    first, second = "https://readhive.org/series/1/1", "https://readhive.org/series/1/2"
    rows = await crawl(adapters.ReadhiveAdapter(), Pages({first: readhive("Complete chapter."), second: FetchHTTPError(404, second)}, first))
    assert len(rows) == 1
    with pytest.raises(FetchHTTPError):
        await crawl(adapters.ReadhiveAdapter(), Pages({first: FetchHTTPError(404, first)}, first))


def test_numeric_prediction_does_not_treat_database_id_as_chapter_number():
    assert base._predict_next_url("https://www.69shuba.com/txt/31604/22525886", 1) == ""
    assert base._predict_next_url("https://fenrirealm.com/series/story/chapter-1", 1) == "https://fenrirealm.com/series/story/chapter-2"
    assert base._predict_next_url("https://readhive.org/series/1/1.5/", 1.5) == ""


@pytest.mark.parametrize("title,number", [("第一章 引子", 1), ("第一百零二章", 102), ("第两千三百一十四章", 2314), ("第一万零三章", 10003)])
def test_chinese_chapter_numbers(title, number):
    assert base.parse_chapter_number("", title) == number


def fenri_page(content, price=0):
    data = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": content}]}]}
    return ('<h2>Chapter 1</h2><div class="chapter-view"><p>Promotional note.</p></div>'
            '<script>const props={chapterData:{id:7,name:"Chapter 1 - Arrival",'
            f'content:{json.dumps(json.dumps(data, ensure_ascii=False)) if content else "null"},'
            'content_format:"json",locked:{price:' + str(price) + '}}};</script>')


@pytest.mark.asyncio
async def test_fenri_reads_svelte_rich_text_without_importing_promotional_note():
    url = "https://fenrirealm.com/series/story/1"
    rows = await crawl(adapters.FenriRealmAdapter(), Pages({url: fenri_page('Hello, 世界. Keep "quotes" and C:\\notes.')}, url, max_chapters=1))
    assert rows[0].title == "Chapter 1 - Arrival"
    assert rows[0].content == 'Hello, 世界. Keep "quotes" and C:\\notes.'
    assert "Promotional" not in rows[0].content


@pytest.mark.asyncio
async def test_fenri_locked_data_is_not_replaced_with_global_note():
    url = "https://fenrirealm.com/series/story/1"
    with pytest.raises(base.PremiumReached):
        await crawl(adapters.FenriRealmAdapter(), Pages({url: fenri_page("", price=5)}, url))


@pytest.mark.asyncio
async def test_boti_uses_api_navigation_and_preserves_text():
    prefix = "https://api.mystorywave.com/story-wave-backend/api/v1/content/chapters/"
    context = Pages({prefix + "4": {"data": {"title": "Chapter 4", "content": "<p>Hello <b>world</b>.</p>", "nextId": 8, "tier": "0"}},
                     prefix + "8": {"data": {"title": "Chapter 5", "content": "<p>Next.</p>", "nextId": None, "paywallStatus": "free"}}},
                    "https://www.botitranslation.com/chapter/4-arrival")
    rows = await crawl(adapters.BotiTranslationAdapter(), context)
    assert [row.number for row in rows] == [4, 5]
    assert rows[0].content == "Hello world."
    assert rows[1].url == "https://www.botitranslation.com/chapter/8"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{"data": []}, {"data": {"title": "Chapter 1", "content": ""}}])
async def test_boti_rejects_bad_or_empty_api_response(response):
    url = "https://api.mystorywave.com/story-wave-backend/api/v1/content/chapters/1"
    with pytest.raises(base.ScrapeError):
        await crawl(adapters.BotiTranslationAdapter(), Pages({url: response}, "https://www.botitranslation.com/chapter/1"))


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gbk", "utf-8"])
async def test_shuba_keeps_https_encoding_and_final_story_sentence(encoding):
    url = "https://www.69shuba.com/txt/1/12345"
    text = '<meta charset="' + encoding + '"><div class="txtnav"><h1>第1章 回家</h1>2020-10-31 作者： 佚名<br>他终于回家了。（本章完）<div class="page1"><a href="/txt/1/12346">下一章</a></div></div>'
    context = Pages({url: text.encode(encoding)}, url, max_chapters=1)
    rows = await crawl(adapters.SixtyNineShubaAdapter(), context)
    assert rows[0].url == url
    assert rows[0].content == "他终于回家了。"
    assert context.calls == [url]


def flight_page(text, next_slug="chapter-2", public=True):
    content = f"<p>{text}</p>"
    chapter = {"chapter_name": "Chapter 1", "chapter_title": 'A "quoted" title', "chapter_content": "$a", "public": public, "price": 0}
    metadata = {"chapter": chapter, "next_chapter": {"chapter_slug": next_slug} if next_slug else None}
    flight = '0:{"unrelated":{"public":false}}\n' + f'a:T{len(content.encode("utf-8")):x},' + content + 'b:' + json.dumps(metadata) + '\n'
    # Splitting the transport across pushes must not change record boundaries.
    midpoint = len(flight) // 2
    return ''.join('<script>self.__next_f.push(' + json.dumps([1, part], ensure_ascii=False) + ')</script>' for part in (flight[:midpoint], flight[midpoint:]))


@pytest.mark.asyncio
async def test_wetried_reads_utf8_byte_lengths_and_decodes_only_once():
    first, second = "https://wetriedtls.com/series/book/chapter-1", "https://wetriedtls.com/series/book/chapter-2"
    text = '世界 🌙 &quot;Hello&quot; C:\\notes'
    context = Pages({first: flight_page(text), second: flight_page("Final.", None)}, first)
    rows = await crawl(adapters.WeTriedTLSAdapter(), context)
    assert rows[0].content == '世界 🌙 "Hello" C:\\notes'
    assert rows[0].title == 'Chapter 1 - A "quoted" title'
    assert context.calls == [first, second]
    assert 'chapter_content' not in rows[0].content


@pytest.mark.asyncio
async def test_wetried_missing_data_is_explicit_failure():
    url = "https://wetriedtls.com/series/book/chapter-1"
    with pytest.raises(base.ScrapeError, match="no chapter data"):
        await crawl(adapters.WeTriedTLSAdapter(), Pages({url: "<html>Blocked</html>"}, url))


def novel543_page(title, text, following):
    return (f'<div class="chapter-content"><h1>{title}</h1><div class="content">{text}</div></div>'
            + (f'<div class="foot-nav"><a href="{following}">下一章</a></div>' if following else ""))


@pytest.mark.asyncio
async def test_novel543_joins_parts_before_numbering_and_respects_chapter_limit():
    first = "https://www.novel543.com/1/8096_11.html"
    second = "https://www.novel543.com/1/8096_11_2.html"
    third = "https://www.novel543.com/1/8096_12.html"
    context = Pages({first: novel543_page("第十一章 回家 (1/2)", "第一段。", second),
                     second: novel543_page("第十一章 回家 (2/2)", "第二段。", third)}, first, max_chapters=1)
    rows = await crawl(adapters.Novel543Adapter(), context)
    assert len(rows) == 1
    assert rows[0].number == 11
    assert rows[0].title == "第十一章 回家"
    assert rows[0].content == "第一段。\n\n第二段。"
    assert rows[0].url == first
    assert context.calls == [first, second]


@pytest.mark.asyncio
async def test_novel543_never_emits_incomplete_split_chapter():
    first, second = "https://www.novel543.com/1/8096_1.html", "https://www.novel543.com/1/8096_1_2.html"
    context = Pages({first: novel543_page("第一章 (1/2)", "第一段。", second), second: FetchHTTPError(503, second)}, first)
    emitted = []
    with pytest.raises(FetchHTTPError):
        async for chapter in adapters.Novel543Adapter().crawl(context):
            emitted.append(chapter)
    assert emitted == []


@pytest.mark.asyncio
async def test_context_does_not_hide_source_http_failure(monkeypatch):
    async def failed(*args, **kwargs):
        raise FetchHTTPError(403, "https://example.com/chapter")
    monkeypatch.setattr(base, "safe_fetch_text", failed)
    context = base.ScrapeContext("https://example.com/chapter", None)
    with pytest.raises(FetchHTTPError):
        await context.fetch_text(context.start_url)


def test_unknown_adapter_is_rejected_and_url_hint_is_exposed():
    with pytest.raises(ValueError, match="Unknown scraper adapter"):
        adapters.get_adapter("unsupported-site")
    assert all(item["start_url_hint"] for item in adapters.list_adapters())
