"""Turn a flat block stream into a draft segmentation plan (the thing the user reviews).

Heuristics first, LLM second. For EPUB the strongest signal is the spine: most books are
one chapter per spine document, so a spine-index change is a boundary; within a single big
spine doc we also break at top-level headings. Each segment is then classified
(frontmatter/chapter/interlude/backmatter), titled, numbered, and grouped under a volume
``part_label``. An optional LLM pass (cheap: titles + first lines + counts, never full text)
refines kinds/titles/numbers and falls back silently if it's unavailable.

The plan is a plain JSON dict (stored in ``import_jobs.plan``) the API can edit in place::

    {"version": 1, "segments": [{"id","kind","title","number","part_label",
      "block_range":[start,end],   # inclusive block indices
      "word_count","first_line","confidence","include"}]}
"""
from __future__ import annotations

import json
import logging
import re

from novelwiki.config.settings import settings
from novelwiki.importer.ir import Document, HEADING, PARAGRAPH, TEXT_KINDS

logger = logging.getLogger(__name__)

PLAN_VERSION = 1

# Title → chapter number, covering English + CJK chapter conventions.
_NUM_PATTERNS = [
    re.compile(r"(?i)chapter\s+(\d+(?:\.\d+)?)"),
    re.compile(r"(?i)\bch\b\.?\s*(\d+(?:\.\d+)?)"),
    re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[章话集回]"),
]
_LEADING_NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)\b")

_FRONT_KW = ("copyright", "title page", "cover", "dedication", "acknowledg", "contents",
             "table of contents", "colophon", "also by", "praise for", "front matter",
             "imprint", "publisher", "isbn", "legal", "disclaimer", "newsletter",
             "foreword", "synopsis", "credits")
_BACK_KW = ("about the author", "back matter", "preview", "teaser", "also available",
            "acknowledgements")
# Readable, unnumbered volume extras: illustration galleries, pathway/world guides, side
# stories. Kept in the book but never assigned a story-chapter number, so they can't collide
# with real chapter numbers and they group under their volume in the TOC.
_EXTRA_KW = ("image gallery", "gallery", "illustration", "artwork", "character sheet",
             "character profile", "characters", "locations", "pathways guide", "pathway guide",
             "world guide", "appendix", "glossary", "side story", "side stories", "audio drama",
             "drama cd", "omake", "bonus chapter", "bonus story", "short story", "afterword")
_PART_RE = re.compile(r"(?i)^\s*(?:volume|book|part|vol\.?|act|arc)\s+([0-9ivxlcdm]+|[a-z]+)\b")
_PROLOGUE_RE = re.compile(r"(?i)\b(prologue|prolog)\b")
_EPILOGUE_RE = re.compile(r"(?i)\b(epilogue|epilog)\b")
_INTERLUDE_RE = re.compile(r"(?i)\b(interlude|intermission|side story)\b")


def _parse_number(title: str) -> float | None:
    if not title:
        return None
    t = re.sub(r"\s+", " ", title)
    for pat in _NUM_PATTERNS:
        m = pat.search(t)
        if m:
            return float(m.group(1))
    m = _LEADING_NUM.match(t)
    if m:
        return float(m.group(1))
    return None


def _word_count(text: str, language: str) -> int:
    if not text:
        return 0
    if (language or "en").lower()[:2] in ("zh", "ja", "ko"):
        return len(re.sub(r"\s+", "", text))
    return len(text.split())


def _dominant_heading_level(blocks) -> int | None:
    levels = [b.level for b in blocks if b.kind == HEADING and b.level]
    return min(levels) if levels else None


def _boundaries(document: Document) -> list[int]:
    """Block indices where a new segment begins: spine-document changes plus top-level
    headings (so a single-file book still splits on its chapter headings)."""
    blocks = document.blocks
    if not blocks:
        return []
    dominant = _dominant_heading_level(blocks)
    bounds = {0}
    prev_spine = blocks[0].loc.get("spine_idx")
    seen_prose_since_bound = False
    for i, b in enumerate(blocks):
        sp = b.loc.get("spine_idx")
        if i > 0 and sp != prev_spine:
            bounds.add(i)
            seen_prose_since_bound = False
        prev_spine = sp
        # Break at a top-level heading only once the current segment already holds prose,
        # so a spine doc's own leading title heading doesn't start an empty segment.
        if b.kind == HEADING and b.level == dominant and seen_prose_since_bound:
            bounds.add(i)
            seen_prose_since_bound = False
        if b.kind in TEXT_KINDS and b.kind != HEADING:
            seen_prose_since_bound = True
    return sorted(bounds)


def _pdf_toc_boundaries(document: Document) -> list[tuple[int, str]] | None:
    """Map a PDF outline to (block_index, title) boundary points: each TOC entry starts at
    the first block on (or after) its 1-based page. Returns None if there's no usable TOC."""
    toc = document.meta.get("pdf_toc") or []
    if len(toc) < 2:
        return None
    # first block index at/after each 0-based page
    first_at_page: dict[int, int] = {}
    for i, b in enumerate(document.blocks):
        p = b.loc.get("page")
        if p is not None and p not in first_at_page:
            first_at_page[p] = i
    if not first_at_page:
        return None
    pages_sorted = sorted(first_at_page)

    def idx_for_page(page0: int) -> int:
        for p in pages_sorted:
            if p >= page0:
                return first_at_page[p]
        return first_at_page[pages_sorted[-1]]

    points: dict[int, str] = {}
    for entry in toc:
        try:
            _level, title, page = entry[0], entry[1], entry[2]
        except (IndexError, TypeError):
            continue
        idx = idx_for_page(max(0, int(page) - 1))
        points.setdefault(idx, str(title).strip())
    points.setdefault(0, points.get(0, ""))
    return sorted(points.items())


def _boundary_points(document: Document) -> list[tuple[int, str | None]]:
    """Ordered (start_index, title_hint) boundaries. PDFs with an outline use it; everything
    else uses spine-document + top-heading boundaries (title_hint resolved from headings)."""
    if document.format == "pdf":
        toc = _pdf_toc_boundaries(document)
        if toc:
            return toc
    return [(i, None) for i in _boundaries(document)]


def _segment_title(blocks, spine_titles: dict, n: int, hint: str | None = None) -> str:
    if hint:
        return hint
    for b in blocks:
        if b.kind == HEADING and b.text:
            return b.text
    sp = blocks[0].loc.get("spine_idx") if blocks else None
    if sp is not None and spine_titles.get(sp):
        return spine_titles[sp]
    return f"Section {n}"


def _first_line(blocks) -> str:
    for b in blocks:
        if b.kind == PARAGRAPH and b.text:
            return b.text[:140]
    for b in blocks:
        if b.text:
            return b.text[:140]
    return ""


def _classify(title: str, number: float | None) -> tuple[str, bool]:
    """Return (kind, include_default) from the title + parsed number.

    A real chapter number (or an explicit "Chapter N") always wins over keyword matching —
    e.g. "Chapter 718: Characters in the Book" is a story chapter, not a character gallery —
    so only genuinely unnumbered sections fall through to extras/front/back matter."""
    low = (title or "").lower()
    if number is not None or re.search(r"(?i)\bchapter\b", low):
        return ("interlude", True) if _INTERLUDE_RE.search(low) else ("chapter", True)
    if _INTERLUDE_RE.search(low):
        return "interlude", True
    if _PROLOGUE_RE.search(low):
        return "chapter", True
    # Readable extras (galleries, guides, side stories, epilogues, afterword): kept, but never
    # numbered as a story chapter. Tagged backmatter so the reader labels them and the commit
    # slots them in the gap after the prior chapter instead of stealing its number.
    if _EPILOGUE_RE.search(low) or any(k in low for k in _EXTRA_KW):
        return "backmatter", True
    if any(k in low for k in _BACK_KW):
        return "backmatter", False
    if any(k in low for k in _FRONT_KW):
        return "frontmatter", False
    return "chapter", True


def build_plan(document: Document) -> dict:
    """Heuristic segmentation → draft plan. Always produces a usable plan with no LLM."""
    blocks = document.blocks
    language = document.meta.get("language", "en")
    spine_titles = {s["spine_idx"]: s.get("title") for s in document.meta.get("spine", [])}
    points = _boundary_points(document)

    raw_segments = []
    for i, (start, hint) in enumerate(points):
        end = (points[i + 1][0] - 1) if i + 1 < len(points) else (len(blocks) - 1)
        seg_blocks = blocks[start:end + 1]
        if not seg_blocks:
            continue
        title = _segment_title(seg_blocks, spine_titles, i + 1, hint)
        number = _parse_number(title)
        kind, include = _classify(title, number)
        wc = sum(_word_count(b.text, language) for b in seg_blocks if b.kind in TEXT_KINDS)
        raw_segments.append({
            "title": title, "number": number, "kind": kind, "include": include,
            "block_range": [start, end], "word_count": wc, "first_line": _first_line(seg_blocks),
        })

    _assign_numbers_and_parts(raw_segments)

    segments = []
    for i, s in enumerate(raw_segments):
        conf = 0.95 if (s["kind"] == "chapter" and s["number"] is not None) else (
            0.85 if s["kind"] == "chapter" else 0.9)
        segments.append({
            "id": f"s{i + 1}",
            "kind": s["kind"],
            "title": s["title"],
            "number": s["number"],
            "part_label": s.get("part_label"),
            "block_range": s["block_range"],
            "word_count": s["word_count"],
            "first_line": s["first_line"],
            "confidence": conf,
            "include": s["include"],
        })
    return {"version": PLAN_VERSION, "segments": segments}


def _assign_numbers_and_parts(segments: list[dict]) -> None:
    """Second pass over heuristic segments: detect volume dividers (→ part_label for the
    chapters that follow) and assign sequential chapter numbers where none was parsed."""
    current_part = None
    next_num = 1
    last_chapter_num = 0.0
    for s in segments:
        title = s["title"] or ""
        is_divider = bool(_PART_RE.match(title)) and s["word_count"] < 60
        if is_divider:
            current_part = title.strip()
            s["kind"] = "frontmatter"      # the divider page itself isn't a chapter
            s["include"] = False
            s["number"] = None
            continue
        # Everything inside a volume's run nests under it in the TOC — including the volume's
        # trailing extras (pathways guide, image gallery) so they group with that volume.
        if current_part and s["kind"] in ("chapter", "interlude", "backmatter"):
            s["part_label"] = current_part
        if s["kind"] == "chapter":
            if _PROLOGUE_RE.search(title.lower()) and s["number"] is None:
                s["number"] = 0.0
            elif s["number"] is None:
                s["number"] = float(next_num)
            last_chapter_num = float(s["number"])
            next_num = int(last_chapter_num) + 1
        elif s["kind"] == "interlude":
            if s["number"] is None:
                s["number"] = round(last_chapter_num + 0.5, 3)


# ── Optional LLM refinement ──────────────────────────────────────────────────

_REFINE_SYSTEM = (
    "You clean up the table of contents of an imported book. You are given an ordered list "
    "of detected segments with their heuristic title, kind, chapter number, word count and "
    "first line. Correct obvious mistakes only. Return STRICT JSON: "
    '{"segments":[{"id","kind","title","number","part_label","include"}]}. '
    "kind is one of chapter|frontmatter|interlude|backmatter. Set include=false for "
    "non-story matter (copyright, table of contents, about the author, ads). Keep every id; "
    "do not merge, split, reorder, or invent segments. number is null for non-chapters."
)


# A confidently-numbered chapter ("Chapter 138" parsed straight from its title) needs no
# second opinion, so only ambiguous segments are sent. On a 1,400-chapter book this shrinks
# the ask from ~1,500 items to a few dozen, so the call stays small and reliable instead of
# overflowing the context and silently falling back to the raw heuristic — exactly the book
# where the heuristic's gallery/guide handling matters most.
_REFINE_BATCH = 150


def _needs_refine(s: dict) -> bool:
    return not (s.get("kind") == "chapter" and s.get("number") is not None
                and (s.get("confidence") or 0) >= 0.95)


async def refine_plan(plan: dict, document: Document) -> dict:
    """Best-effort LLM pass that corrects kinds/titles/numbers/includes for the segments the
    heuristic is unsure about. Any failure (no API key, network, bad JSON) leaves the plan
    unchanged; batches are independent so one bad batch can't sink the rest."""
    if not settings.OPENROUTER_API_KEY:
        return plan
    segs = plan.get("segments", [])
    ambiguous = [s for s in segs if _needs_refine(s)]
    if not ambiguous:
        return plan
    by_id = {s["id"]: s for s in segs}
    book_title = str(document.meta.get("title"))
    for i in range(0, len(ambiguous), _REFINE_BATCH):
        await _refine_batch(ambiguous[i:i + _REFINE_BATCH], by_id, book_title)
    return plan


async def _refine_batch(batch: list[dict], by_id: dict, book_title: str) -> None:
    """Refine one batch of ambiguous segments in place. Isolated try/except: a failed batch
    just leaves its segments on the heuristic result."""
    compact = [
        {"id": s["id"], "title": s["title"], "kind": s["kind"], "number": s["number"],
         "word_count": s["word_count"], "first_line": (s.get("first_line") or "")[:120]}
        for s in batch
    ]
    try:
        from novelwiki.agent.llm_client import call_llm
        from json_repair import repair_json
        messages = [
            {"role": "system", "content": _REFINE_SYSTEM},
            {"role": "user", "content": "Book title: " + book_title +
             "\nSegments:\n" + json.dumps(compact, ensure_ascii=False)},
        ]
        raw = await call_llm(messages, needs_vision=False, model=settings.SEGMENT_MODEL,
                             response_format={"type": "json_object"})
        data = json.loads(repair_json(raw))
    except Exception as e:
        logger.info(f"Segment refinement batch skipped ({type(e).__name__}: {e}); keeping heuristic.")
        return
    for upd in (data.get("segments") or []):
        s = by_id.get(upd.get("id"))
        if not s:
            continue
        if upd.get("kind") in ("chapter", "frontmatter", "interlude", "backmatter"):
            s["kind"] = upd["kind"]
        if isinstance(upd.get("title"), str) and upd["title"].strip():
            s["title"] = upd["title"].strip()
        if "number" in upd:
            s["number"] = upd["number"] if isinstance(upd["number"], (int, float)) else None
        if upd.get("part_label"):
            s["part_label"] = upd["part_label"]
        if isinstance(upd.get("include"), bool):
            s["include"] = upd["include"]
