"""Render a block range into the two shapes a chapter needs.

``render_segment`` returns ``(raw_html, flat_text)``:
  * ``raw_html`` — sanitized rich HTML for the reader (``<p>/<h2>/<blockquote>/<hr>/
    <figure><img>``). Images resolve to ``/assets/<novel_id>/<sha>.<ext>`` URLs.
  * ``flat_text`` — paragraphs joined by blank lines, exactly what ``chunk_chapter_text``
    expects; it drives word count, codex chunking and translation.

Sanitization is defense-in-depth: the inline HTML carried on blocks comes from untrusted
EPUB markup, so when nh3 is available we emit the rich inline and run nh3's allowlist over
the whole fragment; without nh3 we fall back to escaped plain text (structure only), which
is safe by construction. nh3 ships in the web image, so production always takes the rich path.
"""
from __future__ import annotations

from html import escape
from typing import Callable

from novelwiki.importer.ir import (
    HEADING, PARAGRAPH, IMAGE, SCENE_BREAK, CAPTION, FOOTNOTE, TEXT_KINDS,
)

# nh3 allowlist for the reader's rich content.
_ALLOWED_TAGS = {
    "p", "br", "em", "strong", "i", "b", "u", "h2", "h3", "h4", "blockquote",
    "hr", "figure", "img", "figcaption", "sup", "sub", "a", "span", "small", "ul", "ol", "li",
}
_ALLOWED_ATTRS = {
    "img": {"src", "alt", "width", "height", "loading"},
    "a": {"href", "title"},
    "hr": {"class"},
    "p": {"class"},
    "figure": {"class"},
    "figcaption": {"class"},
    "span": {"class"},
}

AssetResolver = Callable[[str], dict | None]   # sha -> {url, width, height, mime} | None


def _load_nh3():
    try:
        import nh3
        return nh3
    except Exception:
        return None


def _heading_tag(level: int | None) -> str:
    # The reader prints the chapter title as <h1>; in-body headings start at <h2>.
    lvl = (level or 1) + 1
    return f"h{min(max(lvl, 2), 4)}"


def _img_html(meta: dict | None) -> str:
    if not meta or not meta.get("url"):
        return ""
    attrs = [f'src="{escape(meta["url"], quote=True)}"', 'loading="lazy"', 'alt=""']
    if meta.get("width"):
        attrs.append(f'width="{int(meta["width"])}"')
    if meta.get("height"):
        attrs.append(f'height="{int(meta["height"])}"')
    return "<img " + " ".join(attrs) + ">"


def render_segment(blocks, asset_resolver: AssetResolver = None) -> tuple[str, str]:
    nh3 = _load_nh3()
    rich = nh3 is not None
    html_parts: list[str] = []
    text_parts: list[str] = []

    def inline(b) -> str:
        # Rich path uses the captured inline HTML (nh3 sanitizes later); plain path escapes.
        if rich and b.loc.get("html"):
            return b.loc["html"]
        return escape(b.text)

    i = 0
    n = len(blocks)
    while i < n:
        b = blocks[i]
        if b.kind == HEADING:
            tag = _heading_tag(b.level)
            html_parts.append(f"<{tag}>{inline(b)}</{tag}>")
        elif b.kind == PARAGRAPH:
            body = f"<p>{inline(b)}</p>"
            if b.loc.get("blockquote"):
                body = f"<blockquote>{body}</blockquote>"
            html_parts.append(body)
        elif b.kind == SCENE_BREAK:
            html_parts.append('<hr class="scene-break">')
        elif b.kind == IMAGE:
            meta = asset_resolver(b.asset_sha) if (asset_resolver and b.asset_sha) else None
            img = _img_html(meta)
            if img:
                # Fold an immediately-following caption into the same <figure>.
                cap = ""
                if i + 1 < n and blocks[i + 1].kind == CAPTION:
                    cap = f"<figcaption>{inline(blocks[i + 1])}</figcaption>"
                    text_parts.append(blocks[i + 1].text)
                    i += 1
                html_parts.append(f"<figure>{img}{cap}</figure>")
        elif b.kind == CAPTION:
            html_parts.append(f'<p class="caption">{inline(b)}</p>')
        elif b.kind == FOOTNOTE:
            html_parts.append(f'<p class="footnote">{inline(b)}</p>')

        if b.kind in TEXT_KINDS and b.text:
            text_parts.append(b.text)
        i += 1

    raw_html = "\n".join(html_parts)
    if rich and raw_html:
        raw_html = nh3.clean(
            raw_html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            link_rel="noopener noreferrer",
        )
    flat_text = "\n\n".join(t.strip() for t in text_parts if t.strip())
    return raw_html, flat_text
