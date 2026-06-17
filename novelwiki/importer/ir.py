"""The normalized intermediate representation every parser emits.

A parser's only job is to turn its format (EPUB XHTML, digital PDF spans, OCR blocks)
into a flat ``Document`` of ``Block``s in reading order. Cleanup, segmentation, preview
and commit then operate purely on this IR — they never see format-specific structures.

The IR is JSON-serializable (``to_dict``/``from_dict``) so the whole block stream can be
checkpointed to disk and a worker can resume an interrupted import across restarts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


# Block kinds. `image`/`scene_break`/`page_break`/`blank` carry no prose; the rest do.
HEADING = "heading"
PARAGRAPH = "paragraph"
IMAGE = "image"
SCENE_BREAK = "scene_break"
PAGE_BREAK = "page_break"
CAPTION = "caption"
FOOTNOTE = "footnote"
BLANK = "blank"

# Kinds that contribute readable prose to the flat text / word count.
TEXT_KINDS = {HEADING, PARAGRAPH, CAPTION, FOOTNOTE}


@dataclass
class Block:
    """One atomic unit of a document in reading order."""
    kind: str
    text: str = ""
    level: int | None = None           # heading depth (1..6)
    asset_sha: str | None = None       # for image blocks: content hash of the bytes
    font_size: float | None = None     # PDF: clustered span size, used for heading promotion
    page: int | None = None            # PDF page index
    confidence: float | None = None    # OCR per-block mean confidence
    loc: dict = field(default_factory=dict)   # {spine_idx,xpath} | {page,bbox} | image {mime,ext,w,h}

    def to_dict(self) -> dict[str, Any]:
        # Drop null/empty fields to keep the on-disk block stream compact.
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, "", {}, [])}

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(
            kind=d["kind"],
            text=d.get("text", ""),
            level=d.get("level"),
            asset_sha=d.get("asset_sha"),
            font_size=d.get("font_size"),
            page=d.get("page"),
            confidence=d.get("confidence"),
            loc=d.get("loc", {}) or {},
        )


@dataclass
class Document:
    """A whole imported book as a flat block stream plus detected metadata.

    ``meta`` carries: title, author, language, description, series, series_index,
    cover_sha, and an ``assets`` map ``{sha: {ext,mime,kind,width,height}}`` describing
    every extracted image so render/commit can resolve them without the original blob.
    """
    blocks: list[Block]
    meta: dict
    format: str               # epub|pdf

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "meta": self.meta,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        return cls(
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
            meta=d.get("meta", {}) or {},
            format=d.get("format", "epub"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "Document":
        return cls.from_dict(json.loads(s))
