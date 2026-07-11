"""A heuristic 0–100 import quality score, computed after parse/segment.

A garbled import (bad OCR, no detected chapters, mojibake, suspiciously short sections)
should be diagnosable at a glance instead of discovered chapter-by-chapter in the reader.
This produces a single score plus the individual factors that fed it, surfaced in the plan
review UI so the user knows whether to trust the auto-segmentation or eyeball it closely.

Pure function of the parsed ``Document`` + the draft plan — no DB, no network.
"""
from __future__ import annotations

from .document import Document, PARAGRAPH, TEXT_KINDS

# Unicode replacement char + common mojibake signatures left when decoding went wrong.
_BAD_CHARS = ("�", "Ã¢", "Ã©", "â€", "Ã\xa0")


def _ratio(num: float, den: float) -> float:
    return (num / den) if den else 0.0


def compute_quality(document: Document, plan: dict) -> dict:
    """Return ``{"score": 0..100, "factors": [{label, ok, detail}]}``."""
    blocks = document.blocks
    meta = document.meta or {}
    segments = plan.get("segments", [])
    included = [s for s in segments if s.get("include")]
    chapters = [s for s in included if s.get("kind") == "chapter"]

    factors: list[dict] = []
    score = 100.0

    # 1. Metadata present (title/author).
    has_title = bool((meta.get("title") or "").strip()) and meta.get("title") not in (
        "Imported book", "Imported PDF")
    has_author = bool((meta.get("author") or "").strip())
    if not has_title:
        score -= 10
    if not has_author:
        score -= 5
    factors.append({"label": "Metadata",
                    "ok": has_title,
                    "detail": "title + author detected" if (has_title and has_author)
                    else ("title only" if has_title else "no title detected")})

    # 2. Did segmentation find chapters at all?
    if not chapters:
        score -= 35
    factors.append({"label": "Chapters",
                    "ok": bool(chapters),
                    "detail": f"{len(chapters)} chapter(s) across {len(segments)} segment(s)"})

    # 3. How many chapters carry a real parsed number (vs. fallback sequencing)?
    numbered = sum(1 for s in chapters if s.get("number") is not None)
    num_ratio = _ratio(numbered, len(chapters))
    if chapters and num_ratio < 0.5:
        score -= 10
    factors.append({"label": "Numbering",
                    "ok": num_ratio >= 0.5 or not chapters,
                    "detail": f"{numbered}/{len(chapters)} chapters numbered"})

    # 4. Suspiciously thin chapters (a sign of bad boundaries / empty extraction).
    short = sum(1 for s in chapters if (s.get("word_count") or 0) < 80)
    short_ratio = _ratio(short, len(chapters))
    if short_ratio > 0.3:
        score -= 15
    factors.append({"label": "Body length",
                    "ok": short_ratio <= 0.3,
                    "detail": f"{short} very short chapter(s)" if short else "chapter lengths look healthy"})

    # 5. Mojibake / replacement characters in the prose.
    sample = "".join(b.text for b in blocks if b.kind in TEXT_KINDS)[:200_000]
    bad = sum(sample.count(c) for c in _BAD_CHARS)
    bad_ratio = _ratio(bad, max(1, len(sample)))
    if bad_ratio > 0.001:
        score -= 15
    factors.append({"label": "Encoding",
                    "ok": bad_ratio <= 0.001,
                    "detail": "clean text" if bad_ratio <= 0.001 else f"{bad} suspicious char(s)"})

    # 6. OCR confidence, when this came through the scanned-PDF path.
    ocr = meta.get("ocr_stats") or {}
    mc = ocr.get("mean_confidence")
    if mc is not None:
        if mc < 0.85:
            score -= 20
        elif mc < 0.92:
            score -= 8
        factors.append({"label": "OCR confidence",
                        "ok": mc >= 0.92,
                        "detail": f"mean {round(mc * 100)}%"})

    # 7. Are there blocks at all / mostly prose?
    prose = sum(1 for b in blocks if b.kind == PARAGRAPH and b.text)
    if prose < 5:
        score -= 20
    factors.append({"label": "Content",
                    "ok": prose >= 5,
                    "detail": f"{prose} paragraph block(s)"})

    score = int(max(0, min(100, round(score))))
    return {"score": score, "factors": factors}
