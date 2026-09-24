from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novelwiki.modules.acquisition.adapters.outbound.importer import ocr_client
from novelwiki.modules.acquisition.adapters.outbound.importer.parsers import pdf_ocr
from novelwiki.platform.config import settings


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    "unreadable response",
    "[]",
    '{}',
    '{"pages":[]}',
    '{"pages":[{"blocks":[]}]}',
    '{"pages":[{"blocks":[]},{"blocks":[{"text":null}]}]}',
])
async def test_gemini_rejects_missing_or_malformed_pages(response):
    async def vision(_messages):
        return response

    with pytest.raises(ValueError, match="OCR"):
        await ocr_client.gemini_ocr(
            [b"page one", b"page two"], runtime=SimpleNamespace(call_vision=vision),
        )


@pytest.mark.asyncio
async def test_gemini_preserves_explicit_blank_page_and_text_order():
    async def vision(_messages):
        return json.dumps({"pages": [
            {"blocks": []},
            {"blocks": [{"kind": "heading", "text": "Chapter 2"}]},
        ]})

    pages = await ocr_client.gemini_ocr(
        [b"blank page", b"chapter page"], runtime=SimpleNamespace(call_vision=vision),
    )

    assert pages[0] == {"blocks": [], "mean_confidence": 0.0}
    assert pages[1]["blocks"][0]["text"] == "Chapter 2"
    assert pages[1]["mean_confidence"] == 0.97


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1, "high", True, None])
def test_ocr_rejects_invalid_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        ocr_client.validate_page_results([{"blocks": [], "mean_confidence": confidence}], 1)


@pytest.fixture
def scanned_document(tmp_path, monkeypatch):
    import fitz

    path = tmp_path / "scan.pdf"
    with fitz.open() as document:
        document.new_page()
        document.new_page()
        document.save(path)
    monkeypatch.setattr(settings, "IMPORT_DIR", str(tmp_path / "imports"))
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_PAGES_PER_REQUEST", 2)
    monkeypatch.setattr(pdf_ocr, "_render", lambda _page: b"page")
    return path


@pytest.mark.asyncio
async def test_incomplete_ocr_batch_is_not_checkpointed(scanned_document, monkeypatch):
    async def incomplete(_images, _lang):
        return [{"blocks": [{"text": "Only one page"}]}]

    monkeypatch.setattr(ocr_client, "gemini_ocr", incomplete)

    with pytest.raises(ValueError, match="exactly one page"):
        await pdf_ocr.parse_pdf_ocr(str(scanned_document), 1, {"gemini_first": True})

    assert pdf_ocr._load_page(1, 0) is None
    assert pdf_ocr._load_page(1, 1) is None


@pytest.mark.asyncio
async def test_complete_checkpoints_resume_without_ocr_provider(scanned_document, monkeypatch):
    for index in range(2):
        pdf_ocr._save_page(1, index, {
            "blocks": [{"text": f"Saved page {index}"}], "mean_confidence": 0.97,
        })

    async def unavailable():
        raise AssertionError("Completed OCR should not contact a provider")

    monkeypatch.setattr(ocr_client, "sidecar_available", unavailable)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")

    document = await pdf_ocr.parse_pdf_ocr(str(scanned_document), 1, {})

    assert [block.text for block in document.blocks] == ["Saved page 0", "Saved page 1"]


@pytest.mark.parametrize("checkpoint", ["{}", '{"blocks":[{"text":12}]}', '{"blocks":'])
def test_invalid_page_checkpoint_is_retried(tmp_path, monkeypatch, checkpoint):
    monkeypatch.setattr(settings, "IMPORT_DIR", str(tmp_path))
    pdf_ocr._page_path(1, 0).write_text(checkpoint, encoding="utf-8")

    assert pdf_ocr._load_page(1, 0) is None
