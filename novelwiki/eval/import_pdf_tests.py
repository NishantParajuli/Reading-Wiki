"""Tests for the PDF import pipeline (S2 digital + S3 scanned/OCR).

Digital-PDF parse, the PDF cleanup passes (reflow/dehyphenation/header strip), TOC-driven
segmentation, scanned detection, and the OCR parser's checkpoint-resume + budget-pause
behaviour (with the sidecar/Gemini calls mocked). All run without a GPU, sidecar, or network.
"""
import io

import pytest

from novelwiki.config.settings import settings
from novelwiki.importer import cleanup, segment, ocr_client, storage
from novelwiki.importer.ir import Block, Document, HEADING, PARAGRAPH, IMAGE
from novelwiki.importer.parsers import pdf_text, pdf_ocr


def _png(w: int, h: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, "PNG")
    return buf.getvalue()


def make_digital_pdf(path: str):
    import fitz
    doc = fitz.open()
    doc.set_metadata({"title": "Tide Manual", "author": "Ada Mariner"})
    p1 = doc.new_page()
    p1.insert_text((72, 80), "Chapter 1", fontsize=22)
    p1.insert_text((72, 130), "Lin woke to the smell of salt and\nsmoke in the moun-\ntains nearby.", fontsize=11)
    p2 = doc.new_page()
    p2.insert_text((72, 80), "Chapter 2", fontsize=22)
    p2.insert_text((72, 130), "The council met at dawn to debate.", fontsize=11)
    doc.set_toc([[1, "Chapter 1", 1], [1, "Chapter 2", 2]])
    doc.save(path)
    doc.close()


def make_scanned_pdf(path: str, pages: int = 2):
    import fitz
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_image(page.rect, stream=_png(300, 400))
    doc.save(path)
    doc.close()


# ── Cleanup (PDF) golden tests ───────────────────────────────────────────────

def test_dehyphenate_preserves_real_compounds():
    assert cleanup.dehyphenate("under-\nstand") == "understand"
    assert cleanup.dehyphenate("moun-\ntains") == "mountains"
    # A capitalized continuation is a real compound, not a wrap — keep the hyphen.
    assert cleanup.dehyphenate("North-\nAmerican") == "North-American"


def test_reflow_paragraph_joins_wrapped_lines():
    assert cleanup.reflow_paragraph("the cat\nsat on\nthe mat") == "the cat sat on the mat"


def test_fix_ligatures():
    assert cleanup.fix_ligatures("ﬁre and ﬂight") == "fire and flight"


def test_clean_document_pdf_reflows_blocks():
    doc = Document([Block(kind=PARAGRAPH, text="the moun-\ntains were\nvery tall", loc={"page": 0})],
                   {"language": "en"}, "pdf")
    cleanup.clean_document(doc)
    assert doc.blocks[0].text == "the mountains were very tall"


def test_strip_running_headers_and_page_numbers():
    blocks = []
    for pg in range(5):
        blocks.append(Block(kind=PARAGRAPH, text="The Tide Manual", page=pg, loc={"page": pg, "edge": "top"}))
        blocks.append(Block(kind=PARAGRAPH, text=f"Body paragraph on page {pg}.", page=pg, loc={"page": pg}))
        blocks.append(Block(kind=PARAGRAPH, text=str(pg + 1), page=pg, loc={"page": pg, "edge": "bottom"}))
    doc = Document(blocks, {"language": "en"}, "pdf")
    cleanup.strip_running_headers(doc)
    texts = [b.text for b in doc.blocks]
    assert "The Tide Manual" not in texts          # running header stripped
    assert all(not t.strip().isdigit() for t in texts)  # bare page numbers stripped
    assert sum("Body paragraph" in t for t in texts) == 5


def test_pdf_cleanup_rejoins_paragraph_split_across_pages():
    doc = Document(
        [
            Block(
                kind=PARAGRAPH, text="The sentence carried", page=0,
                loc={
                    "page": 0, "bbox": [36, 740, 563, 800],
                    "last_line_bbox": [36, 780, 563, 800],
                    "page_width": 595, "page_height": 842,
                },
            ),
            Block(
                kind=PARAGRAPH, text="across the physical page.", page=1,
                loc={
                    "page": 1, "bbox": [36, 36, 300, 55],
                    "last_line_bbox": [36, 36, 300, 55],
                    "page_width": 595, "page_height": 842,
                },
            ),
        ],
        {"language": "en"}, "pdf",
    )
    cleanup.clean_document(doc)
    assert len(doc.blocks) == 1
    assert doc.blocks[0].text == "The sentence carried across the physical page."
    assert doc.blocks[0].loc["end_page"] == 1


def test_pdf_cleanup_keeps_real_paragraph_break_across_pages():
    doc = Document(
        [
            Block(
                kind=PARAGRAPH, text="The first paragraph ended.", page=0,
                loc={
                    "page": 0, "bbox": [36, 740, 300, 800],
                    "last_line_bbox": [36, 780, 300, 800],
                    "page_width": 595, "page_height": 842,
                },
            ),
            Block(
                kind=PARAGRAPH, text="A new paragraph began.", page=1,
                loc={
                    "page": 1, "bbox": [36, 36, 300, 55],
                    "last_line_bbox": [36, 36, 300, 55],
                    "page_width": 595, "page_height": 842,
                },
            ),
        ],
        {"language": "en"}, "pdf",
    )
    cleanup.clean_document(doc)
    assert [block.text for block in doc.blocks] == [
        "The first paragraph ended.", "A new paragraph began.",
    ]


# ── Digital PDF parse + segmentation ─────────────────────────────────────────

@pytest.fixture()
def digital_pdf(tmp_path):
    path = str(tmp_path / "manual.pdf")
    make_digital_pdf(path)
    return path


def test_pdf_text_parse_headings_and_toc(digital_pdf):
    doc = pdf_text.parse_pdf_text(digital_pdf, job_id=991001)
    assert doc.format == "pdf" and doc.meta["scanned"] is False
    assert doc.meta["title"] == "Tide Manual"
    assert len(doc.meta["pdf_toc"]) == 2
    headings = [b.text for b in doc.blocks if b.kind == HEADING]
    assert "Chapter 1" in headings and "Chapter 2" in headings


def test_pdf_digital_cleanup_and_segment(digital_pdf):
    doc = pdf_text.parse_pdf_text(digital_pdf, job_id=991002)
    cleanup.clean_document(doc)
    # Reflow joined the wrapped lines and dehyphenated "moun-/tains".
    body = " ".join(b.text for b in doc.blocks if b.kind == PARAGRAPH)
    assert "mountains" in body and "\n" not in body
    plan = segment.build_plan(doc)
    chapters = [s for s in plan["segments"] if s["kind"] == "chapter"]
    assert [s["title"] for s in chapters] == ["Chapter 1", "Chapter 2"]
    assert [s["number"] for s in chapters] == [1.0, 2.0]


def test_pdf_filename_infers_series_and_volume():
    meta = pdf_text._filename_metadata(
        "/books/Starbound Tales_02 [Publisher]_[R].pdf"
    )
    assert meta == {
        "title": "Starbound Tales — Volume 2",
        "series": "Starbound Tales",
        "series_index": 2.0,
        "volume_label": "Volume 2",
    }


def test_pdf_bare_volume_filename_infers_only_safe_metadata():
    meta = pdf_text._filename_metadata("/books/Vol 2.pdf")
    assert meta == {
        "title": "Vol 2",
        "series_index": 2.0,
        "volume_label": "Volume 2",
    }
    assert "series" not in meta


def test_pdf_filters_micro_decoration_images(tmp_path):
    import fitz
    path = str(tmp_path / "decorations.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Enough searchable body text for a digital PDF.", fontsize=11)
    page.insert_image(fitz.Rect(20, 20, 80, 40), stream=_png(2, 2))
    page.insert_image(fitz.Rect(100, 150, 220, 270), stream=_png(64, 64))
    doc.save(path)
    doc.close()
    job_id = 991004
    try:
        parsed = pdf_text.parse_pdf_text(path, job_id)
        assert len([block for block in parsed.blocks if block.kind == IMAGE]) == 1
        assert len(parsed.meta["assets"]) == 1
        assert parsed.meta["pdf_decorations_skipped"] == 1
    finally:
        storage.cleanup_job(job_id)


def test_pdf_uses_first_full_page_image_as_cover(tmp_path):
    import fitz
    path = str(tmp_path / "cover.pdf")
    doc = fitz.open()
    cover = doc.new_page(width=300, height=400)
    cover.insert_image(cover.rect, stream=_png(300, 400))
    body = doc.new_page(width=300, height=400)
    body.insert_text((30, 80), "Enough searchable text to keep this a digital PDF.", fontsize=11)
    doc.save(path)
    doc.close()
    job_id = 991005
    try:
        parsed = pdf_text.parse_pdf_text(path, job_id)
        assert parsed.meta["scanned"] is False
        assert parsed.meta.get("cover_sha") in parsed.meta["assets"]
        assert parsed.meta["assets"][parsed.meta["cover_sha"]]["kind"] == "cover"
    finally:
        storage.cleanup_job(job_id)


def test_pdf_scanned_detection(tmp_path):
    path = str(tmp_path / "scanned.pdf")
    make_scanned_pdf(path, pages=3)
    doc = pdf_text.parse_pdf_text(path, job_id=991003)
    assert doc.meta["scanned"] is True
    assert doc.meta["page_count"] == 3
    assert doc.blocks == []     # no text blocks emitted; the worker reroutes to OCR


def test_estimate_cost_scales_with_pages():
    settings_pages = pdf_ocr.estimate_cost(600, gemini_first=True, budget_remaining=2000)
    assert settings_pages["scanned_pages"] == 600
    assert settings_pages["est_gemini_requests"] >= 1
    assert settings_pages["budget_remaining"] == 2000
    # Half the escalation when not gemini_first → fewer requests.
    half = pdf_ocr.estimate_cost(600, gemini_first=False, budget_remaining=2000)
    assert half["est_gemini_requests"] < settings_pages["est_gemini_requests"]


# ── OCR parser: resume + budget pause (mocked OCR backends) ───────────────────

def _page_result(text="page text"):
    return {"blocks": [{"kind": "paragraph", "text": text, "confidence": 0.97}], "mean_confidence": 0.97}


@pytest.mark.asyncio
async def test_pdf_ocr_runs_and_resumes(tmp_path, monkeypatch):
    from novelwiki.importer import storage
    path = str(tmp_path / "scan.pdf")
    make_scanned_pdf(path, pages=2)
    job_id = 992001

    calls = {"n": 0}

    async def fake_gemini(images, lang="en"):
        calls["n"] += len(images)
        return [_page_result(f"ocr {i}") for i in range(len(images))]

    async def fake_no_sidecar():
        return False

    monkeypatch.setattr(ocr_client, "gemini_ocr", fake_gemini)
    monkeypatch.setattr(ocr_client, "sidecar_available", fake_no_sidecar)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")

    try:
        doc = await pdf_ocr.parse_pdf_ocr(path, job_id, options={}, progress_cb=None)
        assert doc.meta["scanned"] is True
        assert len([b for b in doc.blocks if b.kind == PARAGRAPH]) == 2
        first_calls = calls["n"]
        assert first_calls == 2

        # Second run must resume entirely from the on-disk page checkpoints (no new OCR calls).
        doc2 = await pdf_ocr.parse_pdf_ocr(path, job_id, options={}, progress_cb=None)
        assert calls["n"] == first_calls
        assert len([b for b in doc2.blocks if b.kind == PARAGRAPH]) == 2
    finally:
        storage.cleanup_job(job_id)


@pytest.mark.asyncio
async def test_pdf_digital_commit_end_to_end(tmp_path):
    """Digital PDF → commit → reader: confirms the 'pdf' source path writes chapters and the
    reader surfaces rich HTML (import source, not raw)."""
    import asyncio
    import asyncpg
    try:
        conn = await asyncio.wait_for(asyncpg.connect(settings.DATABASE_URL), timeout=3)
        await conn.close()
    except Exception:
        pytest.skip("No Postgres reachable; skipping PDF commit integration test.")

    from fastapi import BackgroundTasks
    from novelwiki.db.schema import init_database
    from novelwiki.db.connection import get_db_pool, close_db_pool
    from novelwiki.importer import jobs as import_jobs, commit, storage
    from novelwiki.api.routes import api_get_chapter
    await init_database()

    path = str(tmp_path / "commit.pdf")
    make_digital_pdf(path)
    job_id = await import_jobs.create_job("pdf", path, options={"target": "new"}, status="receiving")
    novel_id = None
    try:
        doc = pdf_text.parse_pdf_text(path, job_id)
        cleanup.clean_document(doc)
        storage.save_blocks(job_id, doc)
        plan = segment.build_plan(doc)
        await import_jobs.update_job(job_id, plan=plan, status="awaiting_review")
        job = await import_jobs.get_job(job_id)
        result = await commit.commit_job(job)
        novel_id = result["novel_id"]
        assert result["stats"]["chapters_written"] == 2

        payload = await api_get_chapter(novel_id, 1.0, BackgroundTasks())
        assert payload["rich_html"] and "<p>" in payload["rich_html"]
        assert "mountains" in payload["content"]
    finally:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if novel_id is not None:
                await conn.execute("DELETE FROM novels WHERE id=$1;", novel_id)
            await conn.execute("DELETE FROM import_jobs WHERE id=$1;", job_id)
        if novel_id is not None:
            storage.cleanup_novel_assets(novel_id)
        storage.cleanup_job(job_id)
        await close_db_pool()


@pytest.mark.asyncio
async def test_pdf_ocr_budget_pause_checkpoints_partial(tmp_path, monkeypatch):
    from novelwiki.importer import storage
    from novelwiki.agent.llm_client import BudgetExhausted
    path = str(tmp_path / "scan2.pdf")
    make_scanned_pdf(path, pages=2)
    job_id = 992002

    calls = {"n": 0}

    async def fake_gemini(images, lang="en"):
        out = []
        for _ in images:
            calls["n"] += 1
            if calls["n"] == 2:
                raise BudgetExhausted("daily budget reached")
            out.append(_page_result(f"ocr {calls['n']}"))
        return out

    async def fake_no_sidecar():
        return False

    monkeypatch.setattr(ocr_client, "gemini_ocr", fake_gemini)
    monkeypatch.setattr(ocr_client, "sidecar_available", fake_no_sidecar)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_PAGES_PER_REQUEST", 1)   # one page per Gemini call

    try:
        with pytest.raises(BudgetExhausted):
            await pdf_ocr.parse_pdf_ocr(path, job_id, options={}, progress_cb=None)
        # Page 0 was checkpointed before the budget ran out; page 1 was not.
        assert pdf_ocr._load_page(job_id, 0) is not None
        assert pdf_ocr._load_page(job_id, 1) is None
    finally:
        storage.cleanup_job(job_id)
