"""Tests for the EPUB import pipeline (S1).

Pure-logic golden tests (cleanup normalization, segmentation boundaries/numbering, EPUB
parse → render) need no DB or network. One end-to-end test imports a fixture EPUB into a
temp novel and asserts the chapters/assets rows + the reader payload, and is skipped if no
Postgres is reachable.
"""
import io
import os
import zipfile

import pytest
import pytest_asyncio

from novelwiki.importer import cleanup, segment, storage
from novelwiki.importer.ir import Block, Document, HEADING, PARAGRAPH, IMAGE
from novelwiki.importer.parsers import epub as epub_parser
from novelwiki.importer.render import render_segment


# ── Fixture EPUB builder ─────────────────────────────────────────────────────

def _png(w: int, h: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 90, 60)).save(buf, "PNG")
    return buf.getvalue()


_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>The Test Tides</dc:title>
    <dc:creator>Ada Mariner</dc:creator>
    <dc:language>en</dc:language>
    <dc:description>A fixture book for the importer.</dc:description>
    <meta name="calibre:series" content="Tideglass"/>
    <meta name="calibre:series_index" content="2"/>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="cover-img" href="cover.png" media-type="image/png" properties="cover-image"/>
    <item id="img1" href="img1.png" media-type="image/png"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="front" href="front.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="front"/>
    <itemref idref="chap1"/>
    <itemref idref="chap2"/>
  </spine>
</package>"""

_NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc"><ol>
<li><a href="chap1.xhtml">Chapter 1</a></li><li><a href="chap2.xhtml">Chapter 2</a></li>
</ol></nav></body></html>"""

_FRONT = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Copyright</h1><p>All rights reserved. &#169; 2026 Ada Mariner.</p></body></html>"""

_CHAP1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chapter 1</h1>
<p>Lin woke to the smell of <em>salt</em> and smoke.</p>
<figure><img src="img1.png" alt="the harbour"/><figcaption>The harbour at dawn.</figcaption></figure>
<hr/>
<p>She had work to do.</p>
</body></html>"""

_CHAP2 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chapter 2</h1>
<p>The council would not <strong>wait</strong>.</p>
<blockquote><p>"Tide waits for no one," he said.</p></blockquote>
</body></html>"""


def make_fixture_epub(path: str):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", _OPF)
        z.writestr("OEBPS/nav.xhtml", _NAV)
        z.writestr("OEBPS/front.xhtml", _FRONT)
        z.writestr("OEBPS/chap1.xhtml", _CHAP1)
        z.writestr("OEBPS/chap2.xhtml", _CHAP2)
        z.writestr("OEBPS/cover.png", _png(4, 6))
        z.writestr("OEBPS/img1.png", _png(8, 5))


# ── Cleanup golden tests ─────────────────────────────────────────────────────

def test_clean_text_dropcap_rejoin():
    assert cleanup.clean_text("T he forest was quiet") == "The forest was quiet"
    assert cleanup.clean_text("W hen the bell rang") == "When the bell rang"
    # Real one-letter words must NOT be glued to the next word.
    assert cleanup.clean_text("A man walked in") == "A man walked in"
    assert cleanup.clean_text("I think so") == "I think so"


def test_clean_text_whitespace_and_zero_width():
    assert cleanup.clean_text("hello\u200bworld") == "helloworld"   # ZWSP stripped
    assert cleanup.clean_text("a\u00a0b   c") == "a b c"            # nbsp -> space, runs collapsed
    assert cleanup.clean_text("  spaced  out  ") == "spaced out"


def test_clean_text_nfc():
    # "e" + combining acute (NFD) -> single NFC codepoint.
    nfd = "cafe\u0301"
    assert cleanup.clean_text(nfd) == "caf\u00e9"


# ── Segmentation golden tests ────────────────────────────────────────────────

def _doc(blocks):
    return Document(blocks=blocks, meta={"language": "en", "spine": []}, format="epub")


def test_segment_boundaries_and_numbering():
    blocks = [
        Block(kind=HEADING, text="Copyright", level=1, loc={"spine_idx": 0}),
        Block(kind=PARAGRAPH, text="All rights reserved.", loc={"spine_idx": 0}),
        Block(kind=HEADING, text="Chapter 1", level=1, loc={"spine_idx": 1}),
        Block(kind=PARAGRAPH, text="Lin woke up.", loc={"spine_idx": 1}),
        Block(kind=HEADING, text="Chapter 2", level=1, loc={"spine_idx": 2}),
        Block(kind=PARAGRAPH, text="The council met.", loc={"spine_idx": 2}),
    ]
    plan = segment.build_plan(_doc(blocks))
    segs = plan["segments"]
    assert len(segs) == 3
    front, c1, c2 = segs
    assert front["kind"] == "frontmatter" and front["include"] is False
    assert c1["kind"] == "chapter" and c1["number"] == 1.0 and c1["include"] is True
    assert c2["kind"] == "chapter" and c2["number"] == 2.0
    # Block ranges are contiguous, inclusive, and cover every block.
    assert front["block_range"] == [0, 1]
    assert c1["block_range"] == [2, 3]
    assert c2["block_range"] == [4, 5]


def test_segment_prologue_and_part_label():
    blocks = [
        Block(kind=HEADING, text="Volume 1", level=1, loc={"spine_idx": 0}),
        Block(kind=HEADING, text="Prologue", level=1, loc={"spine_idx": 1}),
        Block(kind=PARAGRAPH, text="Long ago.", loc={"spine_idx": 1}),
        Block(kind=HEADING, text="Chapter 1", level=1, loc={"spine_idx": 2}),
        Block(kind=PARAGRAPH, text="Now.", loc={"spine_idx": 2}),
    ]
    plan = segment.build_plan(_doc(blocks))
    segs = plan["segments"]
    prologue = next(s for s in segs if "Prologue" in s["title"])
    chapter = next(s for s in segs if "Chapter 1" in s["title"])
    assert prologue["number"] == 0.0
    assert chapter["part_label"] == "Volume 1"


# ── EPUB parse + render ──────────────────────────────────────────────────────

@pytest.fixture()
def fixture_epub(tmp_path):
    path = str(tmp_path / "book.epub")
    make_fixture_epub(path)
    return path


def test_epub_parse_metadata_and_blocks(fixture_epub):
    job_id = 990001
    try:
        doc = epub_parser.parse_epub(fixture_epub, job_id)
        assert doc.meta["title"] == "The Test Tides"
        assert doc.meta["author"] == "Ada Mariner"
        assert doc.meta["series"] == "Tideglass"
        assert doc.meta.get("cover_sha")
        # Cover + inline illustration both registered as assets, with real dimensions.
        assert len(doc.meta["assets"]) == 2
        cover = doc.meta["assets"][doc.meta["cover_sha"]]
        assert cover["kind"] == "cover" and (cover["width"], cover["height"]) == (4, 6)
        kinds = [b.kind for b in doc.blocks]
        assert HEADING in kinds and PARAGRAPH in kinds and IMAGE in kinds
    finally:
        storage.cleanup_job(job_id)


def test_epub_parse_then_render_chapter(fixture_epub):
    job_id = 990002
    try:
        doc = epub_parser.parse_epub(fixture_epub, job_id)
        cleanup.clean_document(doc)
        plan = segment.build_plan(doc)
        # Front matter flagged out; both chapters detected.
        chapters = [s for s in plan["segments"] if s["kind"] == "chapter"]
        assert len(chapters) == 2
        assert any(s["kind"] == "frontmatter" and not s["include"] for s in plan["segments"])

        c1 = chapters[0]
        seg_blocks = doc.blocks[c1["block_range"][0]:c1["block_range"][1] + 1]
        sha = doc.meta["cover_sha"]  # any sha; resolver returns a stable URL

        def resolver(s):
            am = doc.meta["assets"].get(s)
            return {"url": f"/api/assets/novels/9/{s}.{am['ext']}", "width": am["width"], "height": am["height"]} if am else None

        raw_html, flat_text = render_segment(seg_blocks, resolver)
        assert "Lin woke" in flat_text
        # Rich HTML path (nh3 installed): structural tags + the inline illustration survive.
        assert "<p>" in raw_html
        assert "<figure>" in raw_html and "<img" in raw_html
        assert "scene-break" in raw_html
        # Sanitizer must keep our asset URL and drop nothing dangerous (none here).
        assert "/api/assets/novels/9/" in raw_html
    finally:
        storage.cleanup_job(job_id)


# ── End-to-end commit into the DB ────────────────────────────────────────────

@pytest_asyncio.fixture()
async def db_ready():
    import asyncio
    import asyncpg
    from novelwiki.config.settings import settings
    try:
        conn = await asyncio.wait_for(asyncpg.connect(settings.DATABASE_URL), timeout=3)
        await conn.close()
    except Exception:
        pytest.skip("No Postgres reachable; skipping import commit integration test.")
    from novelwiki.db.schema import init_database
    await init_database()
    yield
    from novelwiki.db.connection import close_db_pool
    await close_db_pool()


@pytest.mark.asyncio
async def test_import_commit_end_to_end(tmp_path, db_ready):
    from fastapi import BackgroundTasks
    from novelwiki.importer import jobs as import_jobs, commit
    from novelwiki.db.connection import get_db_pool
    from novelwiki.api.routes import api_get_chapter

    path = str(tmp_path / "e2e.epub")
    make_fixture_epub(path)

    job_id = await import_jobs.create_job("epub", os.path.abspath(path),
                                          options={"target": "new"}, status="receiving")
    novel_id = None
    try:
        doc = epub_parser.parse_epub(path, job_id)
        cleanup.clean_document(doc)
        storage.save_blocks(job_id, doc)
        plan = segment.build_plan(doc)
        await import_jobs.update_job(job_id, plan=plan, status="awaiting_review")

        job = await import_jobs.get_job(job_id)
        result = await commit.commit_job(job)
        novel_id = result["novel_id"]
        assert result["stats"]["chapters_written"] == 2

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            chapters = await conn.fetch(
                "SELECT number, title, kind, content, raw_html FROM chapters WHERE novel_id=$1 ORDER BY number;",
                novel_id)
            assert [float(c["number"]) for c in chapters] == [1.0, 2.0]
            assert all(c["kind"] == "chapter" for c in chapters)
            assert "Lin woke" in chapters[0]["content"]
            assert "<figure>" in chapters[0]["raw_html"]

            assets = await conn.fetch("SELECT kind FROM assets WHERE novel_id=$1;", novel_id)
            kinds = sorted(a["kind"] for a in assets)
            assert "cover" in kinds and "illustration" in kinds

            novel = await conn.fetchrow("SELECT cover_url, title FROM novels WHERE id=$1;", novel_id)
            assert novel["title"] == "The Test Tides"
            assert novel["cover_url"] and novel["cover_url"].startswith(f"/api/assets/novels/{novel_id}/")

        # Reader payload carries sanitized rich HTML for the import source.
        payload = await api_get_chapter(novel_id, 1.0, BackgroundTasks())
        assert payload["rich_html"] and "<p>" in payload["rich_html"]
        assert "Lin woke" in payload["content"]
    finally:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if novel_id is not None:
                await conn.execute("DELETE FROM novels WHERE id=$1;", novel_id)
            await conn.execute("DELETE FROM import_jobs WHERE id=$1;", job_id)
        if novel_id is not None:
            storage.cleanup_novel_assets(novel_id)
        storage.cleanup_job(job_id)
