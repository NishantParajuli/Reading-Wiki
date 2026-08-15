"""Deterministic grounding checks shared by Ask and entity-profile synthesis."""

from __future__ import annotations

import re
from collections.abc import Iterable


# Keep this grammar aligned with the backend citation resolver and frontend renderer.
_CITATION_RE = re.compile(
    r"\[(?:(chunk|fact|rel|relationship|event)s?\s+(\d+)|[^\]]*?\bid\s*(\d+))[^\]]*\]",
    re.IGNORECASE,
)

_EVIDENCE_KEYS = {
    "chunk": "chunk_ids",
    "fact": "fact_ids",
    "rel": "rel_ids",
    "event": "event_ids",
}


def citation_refs(text: str) -> list[tuple[str, int]]:
    """Return de-duplicated citation references in first-appearance order."""
    seen: set[tuple[str, int]] = set()
    refs: list[tuple[str, int]] = []
    for match in _CITATION_RE.finditer(text or ""):
        kind = (match.group(1) or "chunk").lower()
        if kind == "relationship":
            kind = "rel"
        ref = (kind, int(match.group(2) or match.group(3)))
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def evidence_refs(evidence_ids: dict | None) -> set[tuple[str, int]]:
    """Normalize persisted provenance ids into the citation namespace."""
    evidence_ids = evidence_ids or {}
    allowed: set[tuple[str, int]] = set()
    for kind, key in _EVIDENCE_KEYS.items():
        values = evidence_ids.get(key) or []
        if isinstance(values, (str, int)):
            values = [values]
        if not isinstance(values, Iterable):
            continue
        for value in values:
            try:
                allowed.add((kind, int(value)))
            except (TypeError, ValueError):
                continue
    return allowed


def _claim_blocks(markdown: str) -> list[str]:
    """Extract prose/list blocks for conservative citation-coverage checks."""
    blocks: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(" ".join(paragraph))
            paragraph.clear()

    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            flush()
            continue
        if re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", line):
            flush()
            blocks.append(line)
            continue
        paragraph.append(line)
    flush()
    return blocks


def grounding_issues(
    markdown: str,
    evidence_ids: dict | None,
    *,
    require_each_block: bool,
) -> list[str]:
    """Describe machine-checkable grounding failures without echoing story text."""
    allowed = evidence_refs(evidence_ids)
    refs = citation_refs(markdown)
    unsupported = [ref for ref in refs if ref not in allowed]
    issues: list[str] = []

    if unsupported:
        rendered = ", ".join(f"{kind}:{ref_id}" for kind, ref_id in unsupported[:8])
        issues.append(f"citations were not retrieved evidence: {rendered}")

    valid = set(refs) & allowed
    if not valid:
        issues.append("no citation resolves to retrieved evidence")

    if require_each_block:
        uncited = 0
        for block in _claim_blocks(markdown):
            if not (set(citation_refs(block)) & allowed):
                uncited += 1
        if uncited:
            issues.append(f"{uncited} prose/list block(s) lack a retrieved-evidence citation")

    return issues


__all__ = ["citation_refs", "evidence_refs", "grounding_issues"]
