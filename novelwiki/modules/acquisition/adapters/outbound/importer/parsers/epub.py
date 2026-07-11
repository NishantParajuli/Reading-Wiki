"""EPUB → ``ir.Document``.

Pure stdlib + lxml (no ebooklib needed at runtime): open the zip, read the OPF for
metadata + manifest + spine, then walk each spine document in reading order turning its
XHTML into Blocks. Images are extracted to the job's staging dir and referenced by sha;
the cover and any inline illustrations are recorded in ``meta['assets']``.

Guards: encrypted/DRM EPUBs (``META-INF/encryption.xml``) fail with a clear message, and
a zip-bomb cap (entry count + total uncompressed size) bounds untrusted input.
"""
from __future__ import annotations

import logging
import posixpath
import re
import zipfile
from urllib.parse import unquote

from lxml import etree, html as lxml_html

from novelwiki.importer import storage
from novelwiki.importer.ir import (
    Block, Document, HEADING, PARAGRAPH, IMAGE, SCENE_BREAK, CAPTION,
)

logger = logging.getLogger(__name__)

# Zip-bomb guards for untrusted uploads.
_MAX_ENTRIES = 50_000
_MAX_UNCOMPRESSED = 2 * 1024 * 1024 * 1024   # 2 GiB

_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
}

_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}
# Elements whose presence inside a <div>/<section> means "recurse, don't treat as text".
_BLOCK_CHILDREN = {
    "p", "div", "section", "article", "blockquote", "ul", "ol", "li", "figure",
    "table", "header", "footer", "aside", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "pre",
}
_CONTAINERS = {
    "body", "div", "section", "article", "main", "header", "footer", "aside",
    "figure", "ul", "ol", "table", "tbody", "thead", "tr", "blockquote",
}
_SKIP_TAGS = {"script", "style", "head", "nav"}
_INLINE_KEEP = {"em", "strong", "i", "b", "u", "sup", "sub", "br", "a", "span", "small"}
# A short line that is only asterisks/bullets/dashes is a scene divider.
_SCENE_RE = re.compile(r"^[\s\*∗·•—–\-—–~#]{1,12}$")


def _localname(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


class _Epub:
    """Thin reader over the EPUB zip: resolves the OPF, manifest, and spine."""

    def __init__(self, path: str):
        self.zip = zipfile.ZipFile(path, "r")
        self._guard_bomb()
        if any(n.lower().endswith("encryption.xml") for n in self.zip.namelist()):
            raise ValueError("This EPUB is encrypted/DRM-protected and cannot be imported.")
        self.opf_path = self._find_opf()
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.opf = etree.fromstring(self.zip.read(self.opf_path))
        self.manifest: dict[str, dict] = {}     # id → {href, media_type, properties}
        self.href_to_id: dict[str, str] = {}
        self.spine: list[str] = []              # ordered manifest ids
        self._parse_opf()

    def _guard_bomb(self):
        infos = self.zip.infolist()
        if len(infos) > _MAX_ENTRIES:
            raise ValueError(f"EPUB has too many entries ({len(infos)} > {_MAX_ENTRIES}).")
        total = sum(i.file_size for i in infos)
        if total > _MAX_UNCOMPRESSED:
            raise ValueError(f"EPUB uncompressed size {total} exceeds the {_MAX_UNCOMPRESSED}-byte cap.")

    def _find_opf(self) -> str:
        try:
            container = etree.fromstring(self.zip.read("META-INF/container.xml"))
            rootfile = container.find(".//container:rootfile", _NS)
            if rootfile is not None and rootfile.get("full-path"):
                return rootfile.get("full-path")
        except KeyError:
            pass
        for name in self.zip.namelist():
            if name.lower().endswith(".opf"):
                return name
        raise ValueError("No OPF package document found in EPUB.")

    def _parse_opf(self):
        manifest_el = self.opf.find("opf:manifest", _NS)
        if manifest_el is not None:
            for item in manifest_el.findall("opf:item", _NS):
                iid = item.get("id")
                href = item.get("href")
                if not iid or not href:
                    continue
                self.manifest[iid] = {
                    "href": href,
                    "media_type": item.get("media-type", ""),
                    "properties": item.get("properties", "") or "",
                }
                self.href_to_id[self._norm(href)] = iid
        spine_el = self.opf.find("opf:spine", _NS)
        if spine_el is not None:
            for ref in spine_el.findall("opf:itemref", _NS):
                idref = ref.get("idref")
                if idref and idref in self.manifest:
                    self.spine.append(idref)
        self._spine_el = spine_el

    def _norm(self, href: str) -> str:
        """Resolve a manifest/content href (relative to the OPF dir) to a zip path."""
        href = unquote(href.split("#", 1)[0])
        return posixpath.normpath(posixpath.join(self.opf_dir, href))

    def read_item_by_id(self, iid: str) -> bytes:
        return self.zip.read(self._norm(self.manifest[iid]["href"]))

    def read_path(self, zip_path: str) -> bytes:
        return self.zip.read(zip_path)

    def meta_text(self, dc_tag: str) -> str | None:
        el = self.opf.find(f"opf:metadata/dc:{dc_tag}", _NS)
        if el is None:
            el = self.opf.find(f".//dc:{dc_tag}", _NS)
        return (el.text or "").strip() if el is not None and el.text else None

    def opf_meta(self, name: str) -> str | None:
        for m in self.opf.findall(".//opf:meta", _NS):
            if m.get("name") == name:
                return m.get("content")
        return None

    def opf_property(self, prop: str) -> str | None:
        for m in self.opf.findall(".//opf:meta", _NS):
            if m.get("property") == prop and m.text:
                return m.text.strip()
        return None

    def cover_id(self) -> str | None:
        cid = self.opf_meta("cover")
        if cid and cid in self.manifest:
            return cid
        for iid, item in self.manifest.items():
            if "cover-image" in item.get("properties", ""):
                return iid
        return None


# ── XHTML → blocks ───────────────────────────────────────────────────────────

def _inline_html(el) -> str:
    """Inner HTML of a text element, keeping inline markup. nh3 does the final
    allowlisting at render time, so we don't need to be strict here — just drop the
    <img> children (they become their own IMAGE blocks) to avoid duplication."""
    parts = []
    if el.text:
        parts.append(_escape(el.text))
    for child in el:
        if _localname(child.tag) == "img":
            if child.tail:
                parts.append(_escape(child.tail))
            continue
        try:
            parts.append(lxml_html.tostring(child, encoding="unicode"))
        except Exception:
            txt = child.text_content() if hasattr(child, "text_content") else (child.text or "")
            parts.append(_escape(txt))
    return "".join(parts).strip()


def _escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _text_of(el) -> str:
    try:
        return re.sub(r"\s+", " ", el.text_content()).strip()
    except Exception:
        return (el.text or "").strip()


def _has_block_child(el) -> bool:
    for child in el:
        if _localname(child.tag) in _BLOCK_CHILDREN:
            return True
    return False


def _img_src(el) -> str | None:
    for attr in ("src", "{http://www.w3.org/1999/xlink}href", "href"):
        v = el.get(attr)
        if v:
            return v
    return None


def _emit_images(el, epub: _Epub, base_dir: str, blocks: list[Block], meta: dict,
                 job_id: int, spine_idx: int):
    """Extract every <img>/<image> under `el` into IMAGE blocks (in document order)."""
    for img in el.iter():
        if _localname(img.tag) not in ("img", "image"):
            continue
        src = _img_src(img)
        if not src:
            continue
        zip_path = posixpath.normpath(posixpath.join(base_dir, unquote(src.split("#", 1)[0])))
        try:
            data = epub.read_path(zip_path)
        except KeyError:
            logger.warning(f"EPUB image not found in zip: {zip_path}")
            continue
        sha = _register_asset(data, meta, job_id, kind="illustration")
        if not sha:
            continue
        blocks.append(Block(kind=IMAGE, asset_sha=sha, loc={"spine_idx": spine_idx}))
        alt = (img.get("alt") or "").strip()
        if alt:
            blocks.append(Block(kind=CAPTION, text=alt, loc={"spine_idx": spine_idx, "html": _escape(alt)}))


def _register_asset(data: bytes, meta: dict, job_id: int, kind: str) -> str | None:
    """Stage image bytes (dedup by sha) and record them in meta['assets']. Returns sha."""
    mime = _sniff_mime(data)
    try:
        sha, ext = storage.stage_asset(job_id, data, mime)
    except ValueError as e:
        logger.warning("Skipping unsupported EPUB image asset (%s): %s", mime, e)
        return None
    assets = meta.setdefault("assets", {})
    if sha not in assets:
        w, h = _image_size(data)
        assets[sha] = {"ext": ext, "mime": mime, "kind": kind, "width": w, "height": h}
    return sha


def _sniff_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:5] == b"<?xml" or data[:4] == b"<svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _image_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None, None


def _walk(el, epub: _Epub, base_dir: str, blocks: list[Block], meta: dict,
          job_id: int, spine_idx: int, in_quote: bool = False):
    tag = _localname(el.tag)
    if tag in _SKIP_TAGS:
        return
    if tag in _HEADING_TAGS:
        text = _text_of(el)
        if text:
            blocks.append(Block(kind=HEADING, text=text, level=_HEADING_TAGS[tag],
                                loc={"spine_idx": spine_idx, "html": _inline_html(el)}))
        return
    if tag in ("img", "image"):
        _emit_images(el, epub, base_dir, blocks, meta, job_id, spine_idx)
        return
    if tag == "hr":
        blocks.append(Block(kind=SCENE_BREAK, loc={"spine_idx": spine_idx}))
        return
    if tag in ("figure",):
        # figure: images + figcaption, in order.
        for child in el:
            _walk(child, epub, base_dir, blocks, meta, job_id, spine_idx, in_quote=in_quote)
        return
    if tag == "figcaption":
        text = _text_of(el)
        if text:
            blocks.append(Block(kind=CAPTION, text=text, loc={"spine_idx": spine_idx, "html": _inline_html(el)}))
        return

    if tag == "blockquote":
        # A blockquote with block children recurses (its <p>s get the blockquote flag);
        # a bare one becomes a single flagged paragraph.
        if _has_block_child(el):
            for child in el:
                _walk(child, epub, base_dir, blocks, meta, job_id, spine_idx, in_quote=True)
        else:
            text = _text_of(el)
            if text:
                blocks.append(Block(kind=PARAGRAPH, text=text,
                                    loc={"spine_idx": spine_idx, "html": _inline_html(el), "blockquote": True}))
        return

    is_textleaf = tag in ("p", "li", "pre") or (tag in ("div",) and not _has_block_child(el))
    if is_textleaf:
        _emit_images(el, epub, base_dir, blocks, meta, job_id, spine_idx)
        text = _text_of(el)
        if not text:
            return
        if _SCENE_RE.match(text):
            blocks.append(Block(kind=SCENE_BREAK, loc={"spine_idx": spine_idx}))
            return
        loc = {"spine_idx": spine_idx, "html": _inline_html(el)}
        if in_quote:
            loc["blockquote"] = True
        blocks.append(Block(kind=PARAGRAPH, text=text, loc=loc))
        return

    if tag in _CONTAINERS:
        for child in el:
            _walk(child, epub, base_dir, blocks, meta, job_id, spine_idx, in_quote=in_quote)
        return

    # Unknown element with text but no block children → treat as a paragraph.
    if not _has_block_child(el):
        _emit_images(el, epub, base_dir, blocks, meta, job_id, spine_idx)
        text = _text_of(el)
        if text:
            loc = {"spine_idx": spine_idx, "html": _inline_html(el)}
            if in_quote:
                loc["blockquote"] = True
            blocks.append(Block(kind=PARAGRAPH, text=text, loc=loc))
    else:
        for child in el:
            _walk(child, epub, base_dir, blocks, meta, job_id, spine_idx, in_quote=in_quote)


def _parse_spine_doc(data: bytes, epub: _Epub, zip_path: str, blocks: list[Block],
                     meta: dict, job_id: int, spine_idx: int) -> str | None:
    """Parse one XHTML spine document; returns its first heading text (for the TOC)."""
    try:
        root = lxml_html.fromstring(data)
    except Exception as e:
        logger.warning(f"Could not parse spine doc {zip_path}: {e}")
        return None
    body = root.find(".//body")
    if body is None:
        body = root
    base_dir = posixpath.dirname(zip_path)
    start = len(blocks)
    _walk(body, epub, base_dir, blocks, meta, job_id, spine_idx)
    for b in blocks[start:]:
        if b.kind == HEADING:
            return b.text
    return None


def parse_epub(path: str, job_id: int) -> Document:
    """Parse an EPUB file into a normalized Document. `job_id` keys the asset staging dir."""
    epub = _Epub(path)
    meta: dict = {
        "title": epub.meta_text("title"),
        "author": epub.meta_text("creator"),
        "language": (epub.meta_text("language") or "en"),
        "description": epub.meta_text("description"),
        "series": epub.opf_meta("calibre:series") or epub.opf_property("belongs-to-collection"),
        "series_index": epub.opf_meta("calibre:series_index") or epub.opf_property("group-position"),
    }

    # Cover first, so meta['cover_sha'] is set before the spine walk.
    cid = epub.cover_id()
    if cid:
        try:
            cover_sha = _register_asset(epub.read_item_by_id(cid), meta, job_id, kind="cover")
            if cover_sha:
                meta["cover_sha"] = cover_sha
        except Exception as e:
            logger.warning(f"Could not extract cover image: {e}")

    blocks: list[Block] = []
    spine_titles: list[dict] = []
    for spine_idx, iid in enumerate(epub.spine):
        item = epub.manifest[iid]
        mt = item.get("media_type", "")
        if "html" not in mt and "xml" not in mt and not item["href"].lower().endswith((".htm", ".html", ".xhtml")):
            continue
        zip_path = epub._norm(item["href"])
        try:
            data = epub.read_item_by_id(iid)
        except KeyError:
            logger.warning(f"Spine item missing from zip: {zip_path}")
            continue
        title = _parse_spine_doc(data, epub, zip_path, blocks, meta, job_id, spine_idx)
        spine_titles.append({"spine_idx": spine_idx, "title": title, "href": item["href"]})

    meta["spine"] = spine_titles
    if not meta.get("title"):
        meta["title"] = "Imported book"
    doc = Document(blocks=blocks, meta=meta, format="epub")
    logger.info(f"Parsed EPUB '{meta.get('title')}': {len(blocks)} blocks across {len(epub.spine)} spine items.")
    return doc
