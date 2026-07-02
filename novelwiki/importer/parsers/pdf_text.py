"""Digital (born-text) PDF → ``ir.Document`` via PyMuPDF.

We stream the document page by page (PyMuPDF is memory-mapped, so a 600-page book never
loads whole), turning each text block into a PARAGRAPH that still carries its hard line
wraps for ``cleanup`` to reflow, and promoting visually-large/heavy lines to headings by
clustering font sizes. The PDF outline (``get_toc``) is stashed for the segmenter, images
are extracted and anchored in reading order, and pages with little text but a full-page
image are flagged as scanned — if most of the book is scanned the worker reroutes to OCR.
"""
from __future__ import annotations

import logging

from novelwiki.importer import storage
from novelwiki.importer.ir import (
    Block, Document, HEADING, PARAGRAPH, IMAGE, SCENE_BREAK,
)
from novelwiki.importer.parsers.epub import _SCENE_RE, _sniff_mime, _image_size

logger = logging.getLogger(__name__)

# A page with fewer than this many extractable characters AND a near-full-page image is a
# scanned page; once a large fraction of the document is scanned we route the whole job to OCR.
SCANNED_PAGE_TEXT_MIN = 12
SCANNED_PAGE_IMAGE_COVER = 0.5
SCANNED_DOC_FRACTION = 0.6
# Heading promotion: a line at least this much larger than the body font, and short, is a heading.
HEADING_SIZE_RATIO = 1.18
HEADING_MAX_WORDS = 14


def _round_size(s: float) -> float:
    return round(float(s or 0), 1)


def _page_image_bytes(page, block) -> bytes | None:
    """Bytes for an image block, preferring the inline bytes PyMuPDF exposes in dict mode."""
    data = block.get("image")
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return None


def _extract_page(page, page_idx: int, job_id: int, meta: dict, raw_blocks: list[dict]):
    """Pull text + image blocks off one page into intermediate dicts (pre-clustering)."""
    info = page.get_text("dict")
    pw, ph = info.get("width") or page.rect.width, info.get("height") or page.rect.height
    page_area = max(1.0, pw * ph)
    text_chars = 0
    max_img_cover = 0.0
    page_blocks = []

    for blk in info.get("blocks", []):
        bbox = blk.get("bbox", (0, 0, 0, 0))
        if blk.get("type") == 1:  # image
            data = _page_image_bytes(page, blk)
            area = max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            max_img_cover = max(max_img_cover, area / page_area)
            if data:
                page_blocks.append({"kind": IMAGE, "bytes": data, "bbox": bbox, "y": bbox[1]})
            continue
        # text block: assemble lines, preserving line breaks for the reflow pass
        lines, sizes = [], []
        for line in blk.get("lines", []):
            spans = line.get("spans", [])
            txt = "".join(sp.get("text", "") for sp in spans)
            if txt.strip():
                lines.append(txt)
                sizes.extend(sp.get("size", 0) for sp in spans if sp.get("text", "").strip())
        joined = "\n".join(lines).strip()
        if not joined:
            continue
        text_chars += len(joined)
        page_blocks.append({
            "kind": PARAGRAPH, "text": joined, "bbox": bbox, "y": bbox[1],
            "size": _round_size(max(sizes) if sizes else 0),
            "chars": len(joined.replace("\n", "")),
        })

    page_blocks.sort(key=lambda b: (round(b["y"]), b["bbox"][0]))
    # Mark the top/bottom text blocks for running header/footer detection in cleanup.
    text_only = [b for b in page_blocks if b["kind"] == PARAGRAPH]
    if text_only:
        text_only[0]["edge"] = "top"
        text_only[-1]["edge"] = "bottom"

    scanned = text_chars < SCANNED_PAGE_TEXT_MIN and max_img_cover >= SCANNED_PAGE_IMAGE_COVER
    if scanned:
        meta.setdefault("needs_ocr_pages", []).append(page_idx)
    for b in page_blocks:
        b["page"] = page_idx
        raw_blocks.append(b)


def _body_font_size(raw_blocks: list[dict]) -> float:
    """The dominant body font size: the size that the most *characters* are set in."""
    from collections import Counter
    weight: Counter = Counter()
    for b in raw_blocks:
        if b["kind"] == PARAGRAPH and b.get("size"):
            weight[b["size"]] += b.get("chars", 1)
    return weight.most_common(1)[0][0] if weight else 0.0


def _finalize_blocks(raw_blocks: list[dict], job_id: int, meta: dict) -> list[Block]:
    """Cluster font sizes → promote headings, stage images, emit the IR block list."""
    body = _body_font_size(raw_blocks)
    # Rank the distinct heading sizes (largest first) so a level can be assigned.
    big_sizes = sorted({b["size"] for b in raw_blocks
                        if b["kind"] == PARAGRAPH and body and b["size"] >= body * HEADING_SIZE_RATIO},
                       reverse=True)
    size_level = {s: min(i + 1, 4) for i, s in enumerate(big_sizes)}

    blocks: list[Block] = []
    for b in raw_blocks:
        loc = {"page": b["page"], "bbox": [round(x, 1) for x in b["bbox"]]}
        if b.get("edge"):
            loc["edge"] = b["edge"]
        if b["kind"] == IMAGE:
            mime = _sniff_mime(b["bytes"])
            try:
                sha, ext = storage.stage_asset(job_id, b["bytes"], mime)
            except ValueError as e:
                logger.warning("Skipping unsupported PDF image asset (%s): %s", mime, e)
                continue
            assets = meta.setdefault("assets", {})
            if sha not in assets:
                w, h = _image_size(b["bytes"])
                assets[sha] = {"ext": ext, "mime": mime, "kind": "illustration", "width": w, "height": h}
            blocks.append(Block(kind=IMAGE, asset_sha=sha, page=b["page"], loc=loc))
            continue
        text = b["text"]
        if _SCENE_RE.match(text.strip()):
            blocks.append(Block(kind=SCENE_BREAK, page=b["page"], loc=loc))
            continue
        size = b.get("size") or 0
        is_heading = size in size_level and len(text.split()) <= HEADING_MAX_WORDS and "\n" not in text.strip()
        if is_heading:
            blocks.append(Block(kind=HEADING, text=text.strip(), level=size_level[size],
                                font_size=size, page=b["page"], loc=loc))
        else:
            blocks.append(Block(kind=PARAGRAPH, text=text, font_size=size, page=b["page"], loc=loc))
    return blocks


def parse_pdf_text(path: str, job_id: int) -> Document:
    """Parse a digital PDF into a Document. `meta['scanned']` is True when the document is
    mostly page images (the worker then reroutes to the OCR parser)."""
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    md = doc.metadata or {}
    meta: dict = {
        "title": (md.get("title") or "").strip() or None,
        "author": (md.get("author") or "").strip() or None,
        "language": "en",
        "description": (md.get("subject") or "").strip() or None,
        "page_count": doc.page_count,
        "pdf_toc": [list(t) for t in (doc.get_toc(simple=True) or [])],  # [[level,title,page],...]
    }

    raw_blocks: list[dict] = []
    for page_idx in range(doc.page_count):
        _extract_page(doc[page_idx], page_idx, job_id, meta, raw_blocks)

    scanned_pages = len(meta.get("needs_ocr_pages", []))
    meta["scanned"] = doc.page_count > 0 and (scanned_pages / doc.page_count) >= SCANNED_DOC_FRACTION

    if meta["scanned"]:
        # Don't build text blocks for a scanned doc — the worker hands it to the OCR parser.
        doc.close()
        meta["title"] = meta["title"] or "Imported PDF"
        logger.info(f"PDF '{meta['title']}' is scanned ({scanned_pages}/{meta['page_count']} pages); routing to OCR.")
        return Document(blocks=[], meta=meta, format="pdf")

    blocks = _finalize_blocks(raw_blocks, job_id, meta)
    doc.close()
    meta["title"] = meta["title"] or "Imported PDF"
    logger.info(f"Parsed digital PDF '{meta['title']}': {len(blocks)} blocks across {meta['page_count']} pages.")
    return Document(blocks=blocks, meta=meta, format="pdf")
