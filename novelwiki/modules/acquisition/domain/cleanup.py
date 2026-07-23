"""Text cleanup over the IR — shared by every format.

EPUB content is already structured, so it needs only the *light* subset: encoding repair
(ftfy), Unicode NFC (critical so CJK + embeddings are consistent), whitespace/control/
zero-width normalization, and drop-cap rejoin. The heavier PDF-only passes (line reflow,
dehyphenation, running header/footer stripping) land in S2 and will live here too.

Everything operates in place on ``Block.text`` (the canonical plain text used for word
count, codex and translation). The optional rich ``loc['html']`` is lightly normalized but
never reflowed — nh3 is the final gate at render time.
"""
from __future__ import annotations

import logging
import re
import unicodedata

from .document import Document, TEXT_KINDS

logger = logging.getLogger(__name__)

# Zero-width / formatting characters that should never survive into stored text:
# ZWSP, ZWNJ, ZWJ, word-joiner, BOM/ZWNBSP, soft hyphen.
_ZERO_WIDTH = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD], None
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# A leading drop-cap artifact: a single capital (never the words "A"/"I") split from the
# rest of its word, e.g. "T he morning" → "The morning". B-H, J-Z avoids real one-letter words.
_DROPCAP_RE = re.compile(r"^([B-HJ-Zb-hj-z])\s+([a-z])")


def _ftfy(text: str) -> str:
    try:
        import ftfy
        return ftfy.fix_text(text)
    except Exception:
        return text


def clean_text(text: str) -> str:
    """Normalize one run of prose: encoding repair, NFC, drop zero-width/control chars,
    collapse intra-line whitespace, rejoin a leading drop-cap. Idempotent."""
    if not text:
        return ""
    text = _ftfy(text)
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_ZERO_WIDTH)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\xa0", " ").replace("\t", " ")   # nbsp/tab -> plain space
    text = re.sub(r" {2,}", " ", text)
    text = text.strip()
    text = _DROPCAP_RE.sub(r"\1\2", text)
    return text


def clean_html(html: str) -> str:
    """Light normalization for the rich inline fragment: encoding repair + NFC + drop
    zero-width chars. Whitespace is preserved (tags depend on it); nh3 sanitizes later."""
    if not html:
        return ""
    html = _ftfy(html)
    html = unicodedata.normalize("NFC", html)
    html = html.translate(_ZERO_WIDTH)
    return html


# ── PDF-only heavy passes (S2) ───────────────────────────────────────────────
# A digital PDF's text arrives hard-wrapped at the page's visual line width, with words
# split across lines by hyphens and the same running header/footer + page number repeated
# on every page. These passes turn that back into clean, reflowed paragraphs.

# A hyphen at a line break joining a split word. Kept when the continuation is capitalized
# (likely a real compound, e.g. "North-\nAmerican"); removed otherwise ("under-\nstand").
_HYPHEN_BREAK = re.compile(r"(\w)[-‐‑]\s*\n\s*(\w)")
_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}
_PAGE_NUM_RE = re.compile(r"^[\s\-—–]*(?:\d{1,4}|[ivxlcdm]{1,7})[\s\-—–.]*$", re.IGNORECASE)
_PARAGRAPH_TERMINAL_RE = re.compile(r"""[.!?…]["'”’)\]]*$""")


def fix_ligatures(text: str) -> str:
    for lig, rep in _LIGATURES.items():
        if lig in text:
            text = text.replace(lig, rep)
    return text


def dehyphenate(text: str) -> str:
    """Rejoin a word split by a hyphen across a line break, preserving real compounds."""
    def repl(m):
        a, b = m.group(1), m.group(2)
        return f"{a}-{b}" if b.isupper() else f"{a}{b}"
    return _HYPHEN_BREAK.sub(repl, text)


def reflow_paragraph(text: str) -> str:
    """Collapse a hard-wrapped paragraph into one line: dehyphenate, then fold the remaining
    line breaks into spaces."""
    text = dehyphenate(text)
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def reflow_block(text: str) -> list[str]:
    """A PDF text block may hold one or several paragraphs (separated by blank lines).
    Split on blank lines, reflow each, and drop empties."""
    out = []
    for para in re.split(r"\n[ \t]*\n", text):
        r = reflow_paragraph(para)
        if r:
            out.append(r)
    return out


def _running_key(text: str) -> str:
    """Normalize a header/footer line so it matches across pages: lowercased, digits
    blanked (page numbers vary), whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text)).strip().lower()


def strip_running_headers(document: Document) -> None:
    """Remove running headers/footers and bare page numbers in place. A line that sits at a
    page edge and recurs (same digit-blanked text) across a large fraction of pages is
    chrome, not prose; bare page-number lines are dropped wherever they appear."""
    from collections import defaultdict
    pages = {b.loc.get("page") for b in document.blocks if b.loc.get("page") is not None}
    num_pages = len(pages) or 1
    edge_pages: dict[str, set] = defaultdict(set)
    for b in document.blocks:
        if b.text and b.loc.get("edge"):
            edge_pages[_running_key(b.text)].add(b.loc.get("page"))
    threshold = max(3, int(0.4 * num_pages))
    repeated = {k for k, ps in edge_pages.items() if len(k) <= 80 and len(ps) >= threshold}

    kept = []
    for b in document.blocks:
        if b.text:
            t = b.text.strip()
            if _PAGE_NUM_RE.match(t):
                continue
            if b.loc.get("edge") and _running_key(b.text) in repeated:
                continue
        kept.append(b)
    document.blocks = kept


def _pdf_page_continuation(previous, current) -> bool:
    """True when two PDF paragraph blocks are one paragraph split by a physical page.

    A continuation must be the last/first adjacent prose block on consecutive pages and
    reach the page edges. A non-terminal final character is enough; when a sentence happens
    to end exactly at the page boundary, a full-width final line is the stronger geometry
    signal. Headings, scene breaks, and illustrations naturally interrupt adjacency.
    """
    if previous.kind != "paragraph" or current.kind != "paragraph":
        return False
    previous_page = previous.page if previous.page is not None else previous.loc.get("page")
    current_page = current.page if current.page is not None else current.loc.get("page")
    if previous_page is None or current_page != previous_page + 1:
        return False
    previous_box = previous.loc.get("bbox") or []
    current_box = current.loc.get("bbox") or []
    page_height = float(previous.loc.get("page_height") or 0)
    current_height = float(current.loc.get("page_height") or page_height or 0)
    if (
        len(previous_box) != 4
        or len(current_box) != 4
        or not page_height
        or not current_height
        or previous_box[3] < page_height * 0.88
        or current_box[1] > current_height * 0.16
    ):
        return False
    previous_text = previous.text.rstrip()
    current_text = current.text.lstrip()
    if not previous_text or not current_text:
        return False
    if not _PARAGRAPH_TERMINAL_RE.search(previous_text):
        return True
    last_line = previous.loc.get("last_line_bbox") or []
    page_width = float(previous.loc.get("page_width") or 0)
    return (
        len(last_line) == 4
        and page_width > 0
        and float(last_line[2]) >= page_width * 0.88
    )


def merge_pdf_page_continuations(document: Document) -> None:
    """Join paragraph blocks split only because the PDF crossed a physical page."""
    merged = []
    for block in document.blocks:
        if merged and _pdf_page_continuation(merged[-1], block):
            previous = merged[-1]
            previous.text = previous.text.rstrip() + "\n" + block.text.lstrip()
            previous.loc["end_page"] = (
                block.page if block.page is not None else block.loc.get("page")
            )
            previous.loc["last_line_bbox"] = block.loc.get(
                "last_line_bbox", previous.loc.get("last_line_bbox")
            )
            continue
        merged.append(block)
    document.blocks = merged


def _clean_pdf_document(document: Document) -> Document:
    from novelwiki.modules.acquisition.domain.document import Block, PARAGRAPH
    strip_running_headers(document)
    merge_pdf_page_continuations(document)
    kept = []
    for b in document.blocks:
        if b.kind == PARAGRAPH:
            for para in reflow_block(b.text):
                para = clean_text(fix_ligatures(para))
                if para:
                    loc = {k: v for k, v in b.loc.items() if k != "edge"}
                    kept.append(Block(kind=PARAGRAPH, text=para, font_size=b.font_size,
                                      page=b.page or b.loc.get("page"), loc=loc))
        elif b.kind in TEXT_KINDS:
            b.text = clean_text(fix_ligatures(b.text))
            if b.text:
                kept.append(b)
        else:
            kept.append(b)
    document.blocks = kept
    _clean_meta(document)
    return document


def _clean_meta(document: Document) -> None:
    for key in ("title", "author", "description", "series"):
        if document.meta.get(key):
            document.meta[key] = clean_text(str(document.meta[key]))


def clean_document(document: Document) -> Document:
    """Clean every block in place; drop text blocks that normalize to nothing. EPUB takes
    the light path (already structured); PDF additionally reflows + strips page chrome.
    Returns the same document for convenience."""
    if document.format == "pdf":
        return _clean_pdf_document(document)

    kept = []
    for b in document.blocks:
        if b.kind in TEXT_KINDS:
            b.text = clean_text(b.text)
            if not b.text:
                continue
            if "html" in b.loc:
                b.loc["html"] = clean_html(b.loc["html"])
        kept.append(b)
    document.blocks = kept
    # Normalize book metadata strings too (titles/authors carry mojibake just as often).
    _clean_meta(document)
    return document
