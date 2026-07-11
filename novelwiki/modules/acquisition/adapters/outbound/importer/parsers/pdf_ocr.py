"""Scanned PDF → ``ir.Document`` via OCR.

Pages are rendered to images, read by the PaddleOCR sidecar, and any page the sidecar reads
with low mean confidence (or every page, when ``gemini_first``) is escalated to Gemini
vision. Work is checkpointed per page to disk, so a container restart — or a pause when the
Gemini daily budget is exhausted — resumes mid-book instead of starting over. CJK output is
detected and flagged so the import can flow into the translation pipeline as a raw source.
"""
from __future__ import annotations

import json
import logging
import re

from novelwiki.platform.config import settings
from novelwiki.modules.acquisition.adapters.outbound.importer import storage
from novelwiki.modules.acquisition.domain.document import Block, Document, HEADING, PARAGRAPH
from novelwiki.modules.acquisition.adapters.outbound.importer import ocr_client

logger = logging.getLogger(__name__)

OCR_RENDER_DPI = 200
SIDECAR_BATCH = 4
# Hiragana/Katakana, CJK Ext-A, CJK Unified, Hangul — enough to flag a CJK scan as "raw".
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _ocr_dir(job_id: int):
    d = storage.job_dir(job_id) / "ocr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _page_path(job_id: int, idx: int):
    return _ocr_dir(job_id) / f"page_{idx:05d}.json"


def _save_page(job_id: int, idx: int, result: dict) -> None:
    _page_path(job_id, idx).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def _load_page(job_id: int, idx: int) -> dict | None:
    p = _page_path(job_id, idx)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def estimate_cost(scanned_pages: int, gemini_first: bool, budget_remaining: int) -> dict:
    """Rough pre-run estimate for the confirm gate. Without running the sidecar we can't
    know the real escalation rate, so assume all pages escalate under gemini_first, else ~half."""
    import math
    rate = 1.0 if gemini_first else 0.5
    esc_pages = math.ceil(scanned_pages * rate)
    gemini_requests = math.ceil(esc_pages / max(1, settings.GEMINI_PAGES_PER_REQUEST))
    est_minutes = round(gemini_requests / max(1, settings.GEMINI_RPM), 1)
    return {
        "scanned_pages": scanned_pages,
        "est_gemini_requests": gemini_requests,
        "est_minutes": est_minutes,
        "budget_remaining": budget_remaining,
        "gemini_first": gemini_first,
    }


def _render(page) -> bytes:
    pix = page.get_pixmap(dpi=OCR_RENDER_DPI)
    return pix.tobytes("png")


def _detect_language(blocks: list[Block]) -> str:
    sample = "".join(b.text for b in blocks[:200])
    if not sample:
        return "en"
    cjk = len(_CJK_RE.findall(sample))
    return "zh" if cjk / max(1, len(sample)) > 0.15 else "en"


async def parse_pdf_ocr(path: str, job_id: int, options: dict, progress_cb=None) -> Document:
    """OCR a scanned PDF into a Document. Resumes from on-disk page checkpoints; may raise
    BudgetExhausted (the worker pauses the job and retries when the daily budget rolls over)."""
    import fitz
    doc = fitz.open(path)
    total = doc.page_count
    gemini_first = bool(options.get("gemini_first"))
    lang = options.get("lang") or "en"

    have_sidecar = False if gemini_first else await ocr_client.sidecar_available()
    if not have_sidecar and not settings.GEMINI_API_KEY:
        doc.close()
        raise RuntimeError("No OCR backend available: PaddleOCR sidecar is unreachable and GEMINI_API_KEY is unset.")

    remaining = [i for i in range(total) if _load_page(job_id, i) is None]
    done = total - len(remaining)
    if progress_cb:
        await progress_cb(done, total)

    for window in _chunks(remaining, SIDECAR_BATCH):
        images = [_render(doc[i]) for i in window]
        results: dict[int, dict] = {}

        if have_sidecar:
            try:
                sres = await ocr_client.sidecar_ocr(images, lang)
            except Exception as e:
                logger.warning(f"Sidecar OCR failed for pages {window}: {e}; escalating to Gemini.")
                sres = []
            for k, i in enumerate(window):
                if k < len(sres) and sres[k] is not None:
                    results[i] = sres[k]

        # Pages with no good sidecar read (or all pages under gemini_first) go to Gemini.
        escalate = [i for i in window
                    if gemini_first or results.get(i) is None
                    or results[i].get("mean_confidence", 0.0) < settings.OCR_CONFIDENCE_ESCALATE]
        # Checkpoint the confident sidecar pages immediately, so a budget pause keeps them.
        for i in window:
            if i not in escalate and i in results:
                _save_page(job_id, i, results[i])
                done += 1

        for sub in _chunks(escalate, settings.GEMINI_PAGES_PER_REQUEST):
            imgs = [images[window.index(i)] for i in sub]
            gres = await ocr_client.gemini_ocr(imgs, lang)   # may raise BudgetExhausted
            for k, i in enumerate(sub):
                results[i] = gres[k] if k < len(gres) else {"blocks": [], "mean_confidence": 0.0}
                _save_page(job_id, i, results[i])
                done += 1

        if progress_cb:
            await progress_cb(done, total)

    doc_meta = doc.metadata or {}     # `doc` is still open here; closed after assembly below
    blocks: list[Block] = []
    escalations = 0
    conf_sum = conf_n = 0.0
    for i in range(total):
        pr = _load_page(job_id, i) or {"blocks": []}
        mc = pr.get("mean_confidence")
        if mc is not None:
            conf_sum += mc
            conf_n += 1
        if mc is not None and mc >= 0.97:
            escalations += 1
        for b in pr.get("blocks", []):
            text = (b.get("text") or "").strip()
            if not text:
                continue
            kind = HEADING if b.get("kind") in ("heading", "title") else PARAGRAPH
            loc = {"page": i}
            if kind == HEADING:
                blocks.append(Block(kind=HEADING, text=text, level=2, page=i,
                                    confidence=b.get("confidence"), loc=loc))
            else:
                blocks.append(Block(kind=PARAGRAPH, text=text, page=i,
                                    confidence=b.get("confidence"), loc=loc))
    doc.close()

    meta = {
        "title": (doc_meta.get("title") or "").strip() or "Imported PDF",
        "author": (doc_meta.get("author") or "").strip() or None,
        "language": _detect_language(blocks),
        "page_count": total,
        "scanned": True,
        "ocr_stats": {
            "pages": total,
            "mean_confidence": round(conf_sum / conf_n, 3) if conf_n else None,
            "gemini_pages": escalations,
        },
    }
    logger.info(f"OCR complete for job {job_id}: {len(blocks)} blocks, {escalations} Gemini-read pages, lang={meta['language']}.")
    return Document(blocks=blocks, meta=meta, format="pdf")
