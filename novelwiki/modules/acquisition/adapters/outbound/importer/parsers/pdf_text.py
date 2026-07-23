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
import re
from pathlib import Path

from novelwiki.modules.acquisition.adapters.outbound.importer import storage
from novelwiki.modules.acquisition.domain.document import (
    Block, Document, HEADING, PARAGRAPH, IMAGE, SCENE_BREAK,
)
from novelwiki.modules.acquisition.adapters.outbound.importer.parsers.epub import _SCENE_RE, _sniff_mime, _image_size

logger = logging.getLogger(__name__)

# A page with fewer than this many extractable characters AND a near-full-page image is a
# scanned page; once a large fraction of the document is scanned we route the whole job to OCR.
SCANNED_PAGE_TEXT_MIN = 12
SCANNED_PAGE_IMAGE_COVER = 0.5
SCANNED_DOC_FRACTION = 0.6
# Heading promotion: a line at least this much larger than the body font, and short, is a heading.
HEADING_SIZE_RATIO = 1.18
HEADING_MAX_WORDS = 14
# Word/desktop-publishing PDFs often contain 1–2 px bitmap fills for rules, masks, and
# running-page decorations. Treating each one as an illustration creates hundreds of empty
# <figure> gaps in the reader. Real raster art below this size has no useful reading value.
MIN_IMAGE_DIMENSION = 8
# Some generated PDFs report a chapter-heading/footer glyph run with a huge font in the
# bottom margin even though the visible chapter title is represented by the outline. It is
# not usable body text and otherwise lands at the end of the first chapter page.
OUTLINE_ARTIFACT_FONT_RATIO = 2.0
OUTLINE_ARTIFACT_BOTTOM_FRACTION = 0.9

_RELEASE_TAGS_RE = re.compile(r"(?:[\s_-]*\[[^\]]+\])+\s*$")
_BARE_VOLUME_RE = re.compile(
    r"(?i)^vol(?:ume)?\.?[\s_-]*(\d{1,3}(?:\.\d+)?)$"
)
_VOLUME_SUFFIX_RE = re.compile(
    r"(?i)(?:[\s_-]+)(?:vol(?:ume)?\.?\s*)?(\d{1,3}(?:\.\d+)?)$"
)


def _round_size(s: float) -> float:
    return round(float(s or 0), 1)


def _filename_metadata(path: str) -> dict:
    """Best-effort series metadata for PDFs whose embedded metadata is empty.

    Release files commonly look like ``Series Name_02 [Publisher]_[R].pdf``. Keeping the
    volume index lets the series commit sort uploads correctly and gives append-as-volume a
    stable ``Volume N`` label. A bare numeric suffix is intentionally limited to three
    digits so a title ending in a year is not mistaken for a volume.
    """
    stem = _RELEASE_TAGS_RE.sub("", Path(path).stem).strip(" _-")
    bare_match = _BARE_VOLUME_RE.fullmatch(stem)
    if bare_match:
        index = float(bare_match.group(1))
        label = f"Volume {int(index)}" if index.is_integer() else f"Volume {index:g}"
        return {
            "title": re.sub(r"[_-]+", " ", stem).strip(),
            "series_index": index,
            "volume_label": label,
        }
    match = _VOLUME_SUFFIX_RE.search(stem)
    if not match:
        return {}
    series = re.sub(r"\s+", " ", stem[:match.start()].replace("_", " ")).strip(" -_:")
    if not series:
        return {}
    index = float(match.group(1))
    label = f"Volume {int(index)}" if index.is_integer() else f"Volume {index:g}"
    return {
        "title": f"{series} — {label}",
        "series": series,
        "series_index": index,
        "volume_label": label,
    }


def _page_image_bytes(page, block) -> bytes | None:
    """Bytes for an image block, preferring the inline bytes PyMuPDF exposes in dict mode."""
    data = block.get("image")
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return None


def _meaningful_image(block: dict) -> bool:
    try:
        width = int(block.get("width") or 0)
        height = int(block.get("height") or 0)
    except (TypeError, ValueError):
        return True
    if width <= 0 or height <= 0:
        return True
    return width >= MIN_IMAGE_DIMENSION and height >= MIN_IMAGE_DIMENSION


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
            if not _meaningful_image(blk):
                meta["pdf_decorations_skipped"] = int(
                    meta.get("pdf_decorations_skipped") or 0
                ) + 1
                continue
            data = _page_image_bytes(page, blk)
            area = max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            max_img_cover = max(max_img_cover, area / page_area)
            if data:
                page_blocks.append({
                    "kind": IMAGE, "bytes": data, "bbox": bbox, "y": bbox[1],
                    "page_width": float(pw), "page_height": float(ph),
                    "page_cover": area / page_area,
                })
            continue
        # text block: assemble lines, preserving line breaks for the reflow pass
        lines, sizes, line_boxes = [], [], []
        for line in blk.get("lines", []):
            spans = line.get("spans", [])
            txt = "".join(sp.get("text", "") for sp in spans)
            if txt.strip():
                lines.append(txt)
                line_boxes.append(line.get("bbox") or bbox)
                sizes.extend(sp.get("size", 0) for sp in spans if sp.get("text", "").strip())
        joined = "\n".join(lines).strip()
        if not joined:
            continue
        text_chars += len(joined)
        page_blocks.append({
            "kind": PARAGRAPH, "text": joined, "bbox": bbox, "y": bbox[1],
            "size": _round_size(max(sizes) if sizes else 0),
            "chars": len(joined.replace("\n", "")),
            "page_width": float(pw), "page_height": float(ph),
            "first_line_bbox": line_boxes[0], "last_line_bbox": line_boxes[-1],
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
    outline_pages = {
        max(0, int(entry[2]) - 1)
        for entry in (meta.get("pdf_toc") or [])
        if len(entry) >= 3
    }
    # Rank the distinct heading sizes (largest first) so a level can be assigned.
    big_sizes = sorted({b["size"] for b in raw_blocks
                        if b["kind"] == PARAGRAPH and body and b["size"] >= body * HEADING_SIZE_RATIO},
                       reverse=True)
    size_level = {s: min(i + 1, 4) for i, s in enumerate(big_sizes)}

    blocks: list[Block] = []
    for b in raw_blocks:
        loc = {
            "page": b["page"],
            "bbox": [round(x, 1) for x in b["bbox"]],
            "page_width": round(b.get("page_width") or 0, 1),
            "page_height": round(b.get("page_height") or 0, 1),
        }
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
            is_cover = (
                b["page"] == 0
                and b.get("page_cover", 0) >= SCANNED_PAGE_IMAGE_COVER
                and not meta.get("cover_sha")
            )
            if sha not in assets:
                w, h = _image_size(b["bytes"])
                assets[sha] = {
                    "ext": ext, "mime": mime,
                    "kind": "cover" if is_cover else "illustration",
                    "width": w, "height": h,
                }
            if is_cover:
                meta["cover_sha"] = sha
            blocks.append(Block(kind=IMAGE, asset_sha=sha, page=b["page"], loc=loc))
            continue
        text = b["text"]
        if _SCENE_RE.match(text.strip()):
            blocks.append(Block(kind=SCENE_BREAK, page=b["page"], loc=loc))
            continue
        size = b.get("size") or 0
        page_height = b.get("page_height") or 0
        if (
            body
            and b["page"] in outline_pages
            and size >= body * OUTLINE_ARTIFACT_FONT_RATIO
            and page_height
            and b["bbox"][1] >= page_height * OUTLINE_ARTIFACT_BOTTOM_FRACTION
        ):
            meta["pdf_text_artifacts_skipped"] = int(
                meta.get("pdf_text_artifacts_skipped") or 0
            ) + 1
            continue
        if b.get("first_line_bbox"):
            loc["first_line_bbox"] = [
                round(x, 1) for x in b["first_line_bbox"]
            ]
        if b.get("last_line_bbox"):
            loc["last_line_bbox"] = [
                round(x, 1) for x in b["last_line_bbox"]
            ]
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
    inferred = _filename_metadata(path)
    meta: dict = {
        "title": (md.get("title") or "").strip() or inferred.get("title"),
        "author": (md.get("author") or "").strip() or None,
        "language": "en",
        "description": (md.get("subject") or "").strip() or None,
        "page_count": doc.page_count,
        "pdf_toc": [list(t) for t in (doc.get_toc(simple=True) or [])],  # [[level,title,page],...]
    }
    for key in ("series", "series_index", "volume_label"):
        if inferred.get(key) is not None:
            meta[key] = inferred[key]

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
