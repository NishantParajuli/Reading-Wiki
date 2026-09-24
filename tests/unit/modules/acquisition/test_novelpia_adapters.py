"""Independent adapter regressions using only synthetic prose and archives."""
from __future__ import annotations

import base64
import io
import stat
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from novelwiki.modules.acquisition.adapters.outbound.importer.parsers import epub
from novelwiki.modules.acquisition.adapters.outbound.scraper import novelpia, raw_archive
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import ScrapeError


BOOK = "a" * 40
OTHER_BOOK = "b" * 40
CATALOG = "https://fucknovelpia.com/novel/synthetic"
RAW_CATALOG = "https://raw-fucknovelpia.com/novel/synthetic"


def chapter_url(number, *, book=BOOK, host="fucknovelpia.com", token=""):
    return f"https://{host}/chapter.php?hash={book}&ch={number}" + (f"&token={token}" if token else "")


def reader(body="<p>The <em>red</em> door.<br>A second line.</p>", *, next_url=None, heading="Chapter 1"):
    nav = f'<a id="chapter-next-link" href="{next_url}">Next</a>' if next_url else ""
    return f'<div class="reader"><h1>{heading}</h1>{body}</div>{nav}<p>Unrelated site footer</p>'


def context(start, pages, *, limit=None, data=None, config=None):
    return SimpleNamespace(
        start_url=start, max_chapters=limit, config=config or {},
        fetch_text=AsyncMock(side_effect=lambda url: pages.get(url)),
        fetch_bytes=AsyncMock(return_value=data),
    )


async def collect(adapter, ctx):
    return [chapter async for chapter in adapter.crawl(ctx)]


def zip_bytes(entries, *, compression=zipfile.ZIP_DEFLATED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as archive:
        for name, body in entries:
            archive.writestr(name, body)
    return stream.getvalue()


def epub_bytes():
    package = (
        '<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<metadata><dc:title>Synthetic Story</dc:title><dc:language>en</dc:language></metadata>'
        '<manifest><item id="second" href="second.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="first" href="first.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/></manifest>'
        '<spine><itemref idref="first"/><itemref idref="second"/></spine></package>'
    )
    return zip_bytes([
        ("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>'),
        ("book.opf", package),
        ("second.xhtml", '<html><body><h1>Chapter 2</h1><p>Second synthetic chapter.</p></body></html>'),
        ("first.xhtml", '<html><body><h1>Chapter 1</h1><p>First synthetic chapter.</p><img src="cover.png" alt="Synthetic cover"/></body></html>'),
        ("cover.png", b"\x89PNG\r\n\x1a\nsynthetic-image"),
    ])


def toc_epub_bytes(kind, *, explicit_heading=False, entity=False):
    if kind == "ncx":
        manifest = '<item id="toc" href="nav/toc.ncx" media-type="application/x-dtbncx+xml"/>'
        toc_name = "OPS/nav/toc.ncx"
        toc = (
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
            '<navPoint><navLabel><text>Chapter 2: Second</text></navLabel><content src="../second.xhtml"/></navPoint>'
            '<navPoint><navLabel><text>Chapter 1: First</text></navLabel><content src="../first%20part.xhtml#scene"/></navPoint>'
            '</navMap></ncx>'
        )
    else:
        manifest = '<item id="toc" href="nav/toc.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        toc_name = "OPS/nav/toc.xhtml"
        toc = (
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>'
            '<nav epub:type="toc"><ol><li><a href="../second.xhtml">Chapter 2: Second</a></li>'
            '<li><a href="../first%20part.xhtml#scene">Chapter 1: First</a></li></ol></nav></body></html>'
        )
    if entity:
        toc = '<!DOCTYPE html [<!ENTITY injected "Expanded text">]>' + toc
    package = (
        '<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<metadata><dc:title>Synthetic Story</dc:title></metadata><manifest>' + manifest +
        '<item id="title" href="title.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="first" href="first part.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="second" href="second.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="title"/><itemref idref="first"/><itemref idref="second"/></spine></package>'
    )
    heading = '<h1>Chapter 1: Explicit heading</h1>' if explicit_heading else ""
    return zip_bytes([
        ("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>'),
        ("OPS/book.opf", package), (toc_name, toc),
        ("OPS/title.xhtml", '<html><body><p>Synthetic Story</p></body></html>'),
        ("OPS/first part.xhtml", f'<html><body>{heading}<p>First synthetic prose.</p></body></html>'),
        ("OPS/second.xhtml", '<html><body><p>Second synthetic prose.</p></body></html>'),
    ])


@pytest.mark.asyncio
async def test_translated_catalog_skips_image_cover_and_persists_canonical_urls():
    zero, first, second = chapter_url(0, token="one"), chapter_url(1, token="two"), chapter_url(2, token="three")
    ctx = context(CATALOG, {
        CATALOG: f'<div id="chapter-list"><a href="{zero}">Cover</a><a href="{first}">Chapter 1</a></div>',
        zero: reader('<img src="cover.jpg">', next_url=first, heading="Cover"),
        first: reader(next_url=second), second: reader("<p>Second chapter.</p>", heading="Chapter 2"),
    })
    result = await collect(novelpia.FuckNovelpiaAdapter(), ctx)
    assert [chapter.number for chapter in result] == [1, 2]
    assert [chapter.url for chapter in result] == [chapter_url(1), chapter_url(2)]
    assert result[0].content == "The red door.\nA second line."
    assert "Unrelated site footer" not in result[0].content
    assert ctx.fetch_text.await_count == 4


def test_canonical_checkpoint_strips_transient_queries_and_fragments():
    assert novelpia.canonical_chapter_url(chapter_url(2, token="temporary") + "&expires=123#reader") == chapter_url(2)


@pytest.mark.parametrize("url", [chapter_url(1) + "&ch=2", chapter_url(1) + "&hash=" + OTHER_BOOK, chapter_url("9" * 400)])
def test_translated_ambiguous_or_nonfinite_identity_is_rejected(url):
    assert novelpia.chapter_identity(url) is None
    with pytest.raises(ScrapeError):
        novelpia.canonical_chapter_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [chapter_url(1, host="attacker.invalid"), chapter_url(1).replace("https:", "ftp:"), "https://fucknovelpia.com/"])
async def test_translated_invalid_start_is_rejected_before_fetch(url):
    ctx = context(url, {})
    with pytest.raises(ScrapeError):
        await collect(novelpia.FuckNovelpiaAdapter(), ctx)
    ctx.fetch_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("next_url", [chapter_url(2, book=OTHER_BOOK), chapter_url(2, host="attacker.invalid"), chapter_url(1, token="different"), chapter_url(0)])
async def test_translated_bad_next_links_fail_without_fetching_them(next_url):
    first = chapter_url(1)
    ctx = context(first, {first: reader(next_url=next_url)})
    with pytest.raises(ScrapeError):
        await collect(novelpia.FuckNovelpiaAdapter(), ctx)
    assert ctx.fetch_text.await_count == 1


@pytest.mark.asyncio
async def test_translated_catalog_cannot_send_reader_to_external_host():
    external = chapter_url(1, host="attacker.invalid")
    ctx = context(CATALOG, {CATALOG: f'<div id="chapter-list"><a href="{external}">Chapter 1</a></div>', external: reader()})
    with pytest.raises(ScrapeError, match="host|URL"):
        await collect(novelpia.FuckNovelpiaAdapter(), ctx)
    assert ctx.fetch_text.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("html", [None, "<main>Maintenance</main>", reader("")])
async def test_translated_missing_reader_is_not_success(html):
    first = chapter_url(1)
    with pytest.raises(ScrapeError):
        await collect(novelpia.FuckNovelpiaAdapter(), context(first, {first: html}))


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 1])
async def test_translated_chapter_limit_does_not_fetch_next(limit):
    first = chapter_url(1)
    ctx = context(first, {first: reader(next_url=chapter_url(2))}, limit=limit)
    assert len(await collect(novelpia.FuckNovelpiaAdapter(), ctx)) == limit
    assert ctx.fetch_text.await_count == limit


@pytest.mark.asyncio
async def test_translated_heading_fallback_preserves_decimal_number():
    first = chapter_url(1.5)
    result = await collect(novelpia.FuckNovelpiaAdapter(), context(first, {first: '<div class="reader"><p>Decimal chapter.</p></div>'}))
    assert result[0].title == "Chapter 1.5"


def test_epub_text_mode_preserves_spine_without_writing_assets(monkeypatch):
    stage = Mock(side_effect=AssertionError("Text mode must not stage assets"))
    monkeypatch.setattr(epub.storage, "stage_asset", stage)
    document = epub.parse_epub(io.BytesIO(epub_bytes()), None)
    assert [block.text for block in document.blocks] == ["Chapter 1", "First synthetic chapter.", "Chapter 2", "Second synthetic chapter."]
    assert not document.meta.get("assets") and not document.meta.get("cover_sha")
    stage.assert_not_called()


@pytest.mark.parametrize("kind", ["ncx", "nav"])
def test_epub_toc_fallback_labels_keep_spine_order_and_skip_plain_title_page(kind):
    data = toc_epub_bytes(kind)
    document = epub.parse_epub(io.BytesIO(data), None)
    assert [entry["title"] for entry in document.meta["spine"]] == [None, "Chapter 1: First", "Chapter 2: Second"]
    chapters = raw_archive.archive_chapters(data, "", RAW_CATALOG)
    assert [chapter.title for chapter in chapters] == ["Chapter 1: First", "Chapter 2: Second"]
    assert [chapter.number for chapter in chapters] == [1, 2]
    assert chapters[0].content == "First synthetic prose."


@pytest.mark.parametrize("kind", ["ncx", "nav"])
def test_epub_explicit_heading_takes_precedence_over_toc_fallback(kind):
    document = epub.parse_epub(io.BytesIO(toc_epub_bytes(kind, explicit_heading=True)), None)
    assert document.meta["spine"][1]["title"] == "Chapter 1: Explicit heading"


@pytest.mark.parametrize("kind", ["ncx", "nav"])
def test_epub_toc_fallback_rejects_entity_declarations(kind):
    with pytest.raises(ValueError, match="entity"):
        epub.parse_epub(io.BytesIO(toc_epub_bytes(kind, entity=True)), None)


def test_raw_nested_epub_and_txt_follow_natural_then_spine_order(monkeypatch):
    monkeypatch.setattr(epub.storage, "stage_asset", Mock(side_effect=AssertionError("No asset writes")))
    data = zip_bytes([
        ("10.txt", "Chapter 30\nFinal synthetic chapter."),
        ("2.epub", epub_bytes()),
        ("1.txt", "Chapter 10\nInitial synthetic chapter."),
        ("__MACOSX/ignored.txt", "Ignore this platform metadata."),
    ])
    chapters = raw_archive.archive_chapters(data, "", RAW_CATALOG)
    assert [chapter.number for chapter in chapters] == [1, 2, 3, 4]
    assert [chapter.title for chapter in chapters] == ["Chapter 10", "Chapter 1", "Chapter 2", "Chapter 30"]
    assert all(chapter.url == f"{RAW_CATALOG}#tideglass-chapter={index}" for index, chapter in enumerate(chapters, 1))
    resumed = raw_archive.archive_chapters(data, "", RAW_CATALOG, resume_index=3, limit=1)
    assert [chapter.number for chapter in resumed] == [3]
    assert raw_archive.archive_chapters(data, "", RAW_CATALOG, resume_index=5) == []


def test_raw_limit_stops_before_opening_later_damaged_member():
    data = zip_bytes([("1.txt", "Chapter 1\nFirst prose."), ("2.epub", b"damaged epub")])
    chapters = raw_archive.archive_chapters(data, "", RAW_CATALOG, limit=1)
    assert len(chapters) == 1 and chapters[0].content == "First prose."


def test_raw_zero_limit_does_not_open_archive():
    assert raw_archive.archive_chapters(b"not even a zip", "", RAW_CATALOG, limit=0) == []


def test_raw_direct_epub_and_utf16_text_are_supported():
    assert [chapter.title for chapter in raw_archive.archive_chapters(epub_bytes(), "", RAW_CATALOG)] == ["Chapter 1", "Chapter 2"]
    chapters = raw_archive.archive_chapters(zip_bytes([("1.txt", "1화\n첫 번째 합성 장.\n2화\n두 번째 합성 장.".encode("utf-16"))]), "", RAW_CATALOG)
    assert [chapter.title for chapter in chapters] == ["1화", "2화"]


def test_raw_html_keeps_prose_but_not_scripts_or_navigation():
    data = zip_bytes([("chapter.html", "<h1>A synthetic chapter</h1><p>Keep <em>this</em> text.</p><script>bad()</script><nav><p>Skip navigation</p></nav>")])
    chapter = raw_archive.archive_chapters(data, "", RAW_CATALOG)[0]
    assert chapter.title == "A synthetic chapter"
    assert chapter.content == "Keep this text."


# Tiny ZIP produced from synthetic text by libarchive's traditional ZIP encryption.
# Its public test password is fixture-password, unrelated to any source credentials.
ENCRYPTED_FIXTURE = base64.b64decode(
    "UEsDBBQACQAIAFKmNl0AAAAAAAAAAAAAAAAFACAAMS50eHR1eAsAAQToAwAABOgDAABVVA0AB0GZsmpBmbJqQZmyakwLZeMwlxffRWBgGZA7S0s/KV67CfcOEPo4n0x5bVyFwS2b4fQ5CcV02+yAyRsA4lBLBwjzzc7bMAAAACIAAABQSwECFAMUAAkACABSpjZd883O2zAAAAAiAAAABQAYAAAAAAAAAAAApIEAAAAAMS50eHR1eAsAAQToAwAABOgDAABVVAUAAUGZsmpQSwUGAAAAAAEAAQBLAAAAgwAAAAAA"
)


@pytest.mark.parametrize("password", ["", "wrong-fixture-password"])
def test_raw_encrypted_zip_requires_correct_password(password):
    with pytest.raises(ScrapeError, match="password") as error:
        raw_archive.archive_chapters(ENCRYPTED_FIXTURE, password, RAW_CATALOG)
    assert "wrong-fixture-password" not in str(error.value)


def test_raw_encrypted_zip_success_does_not_retain_password():
    result = raw_archive.archive_chapters(ENCRYPTED_FIXTURE, "fixture-password", RAW_CATALOG)
    assert result[0].content == "Synthetic locked prose."
    assert "fixture-password" not in repr(result)


@pytest.mark.parametrize("data", [b"not a ZIP", zip_bytes([("1.epub", b"bad epub")]), zip_bytes([("image.png", b"image only")])])
def test_raw_malformed_or_image_only_archive_is_actionable_error(data):
    with pytest.raises(ScrapeError):
        raw_archive.archive_chapters(data, "", RAW_CATALOG)


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "folder/../../escape.txt", "folder\\..\\escape.txt"])
def test_raw_unsafe_member_paths_are_rejected(name):
    with pytest.raises(ScrapeError, match="unsafe"):
        raw_archive.archive_chapters(zip_bytes([(name, "Synthetic prose.")]), "", RAW_CATALOG)


def test_raw_symlink_member_is_rejected():
    link = zipfile.ZipInfo("link.txt")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ScrapeError, match="unsafe"):
        raw_archive.archive_chapters(zip_bytes([(link, "target.txt")]), "", RAW_CATALOG)


@pytest.mark.parametrize("limit_name,limit", [("MAX_ARCHIVE_ENTRIES", 0), ("MAX_MEMBER_BYTES", 3), ("MAX_ARCHIVE_BYTES", 3)])
def test_raw_archive_limits_apply_before_member_read(monkeypatch, limit_name, limit):
    monkeypatch.setattr(raw_archive, limit_name, limit)
    with pytest.raises(ScrapeError, match="limit"):
        raw_archive.archive_chapters(zip_bytes([("chapter.txt", "A little synthetic prose.")]), "", RAW_CATALOG)


def test_raw_nested_epub_expanded_size_is_guarded(monkeypatch):
    inner = zip_bytes([("padding.txt", "a" * 20_000)])
    assert len(inner) < 1000
    monkeypatch.setattr(raw_archive, "MAX_ARCHIVE_BYTES", 1000)
    data = zip_bytes([("1.epub", inner)])
    with pytest.raises(ScrapeError, match="limit"):
        raw_archive.archive_chapters(data, "", RAW_CATALOG)


@pytest.mark.asyncio
async def test_raw_adapter_refreshes_download_and_resumes_from_stable_catalog():
    download = "https://raw-fucknovelpia.com/download.php?hash=" + BOOK + "&token=temporary"
    ctx = context(RAW_CATALOG + "#tideglass-chapter=2", {RAW_CATALOG: f'<a href="{download}">Download</a>'},
                  data=zip_bytes([("chapters.txt", "Chapter 1\nFirst prose.\nChapter 2\nSecond prose.\nChapter 3\nThird prose.")]), limit=1)
    result = await collect(raw_archive.RawFuckNovelpiaAdapter(), ctx)
    assert len(result) == 1 and result[0].number == 2
    assert result[0].url == RAW_CATALOG + "#tideglass-chapter=2"
    ctx.fetch_text.assert_awaited_once_with(RAW_CATALOG)
    ctx.fetch_bytes.assert_awaited_once_with(download, raise_errors=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("link", ["", '<a href="https://attacker.invalid/download.php">Download</a>'])
async def test_raw_missing_or_external_download_is_not_fetched(link):
    ctx = context(RAW_CATALOG, {RAW_CATALOG: link})
    with pytest.raises(ScrapeError):
        await collect(raw_archive.RawFuckNovelpiaAdapter(), ctx)
    ctx.fetch_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_zero_limit_does_not_download():
    ctx = context(RAW_CATALOG, {}, limit=0)
    assert await collect(raw_archive.RawFuckNovelpiaAdapter(), ctx) == []
    ctx.fetch_text.assert_not_awaited()
    ctx.fetch_bytes.assert_not_awaited()
