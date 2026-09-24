"""OCR routing for scanned pages: a local PaddleOCR sidecar first, Gemini vision as the
quality escalation for pages the sidecar reads poorly.

Pixels go to Gemini (free-tier quota, guarded by the budget + RPM limiter in llm_client);
layout-aware text comes from the GPU sidecar (separate deploy on :8077). The page-result
contract both speak is::

    {"blocks": [{"kind": "paragraph|heading", "text": str, "confidence": float, "bbox": [..]}],
     "mean_confidence": float}

The sidecar runs out-of-process so the web image stays GPU-free; this module is just the
HTTP client + the Gemini fallback, and degrades gracefully when one provider is missing.
"""
from __future__ import annotations

import base64
import json
import logging
import math

import httpx

from novelwiki.platform.config import settings

logger = logging.getLogger(__name__)


def validate_page_results(pages, expected_pages: int) -> list[dict]:
    """Reject incomplete OCR output before it can become a durable blank page."""
    if not isinstance(pages, list) or len(pages) != expected_pages:
        raise ValueError("OCR response must contain exactly one page per input image.")
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("blocks"), list):
            raise ValueError("OCR page must contain a blocks list.")
        for block in page["blocks"]:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                raise ValueError("OCR blocks must contain text strings.")
        for item, key in [(page, "mean_confidence"), *(
            (block, "confidence") for block in page["blocks"]
        )]:
            confidence = item.get(key)
            if (confidence is not None or (key == "mean_confidence" and key in item)) and (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError("OCR confidence must be a finite number between zero and one.")
    return pages


def _data_url(image: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


def _auth_headers() -> dict[str, str]:
    """Shared service token the sidecar requires when configured (empty → send no header)."""
    tok = settings.ocr_sidecar_token
    return {"X-Tideglass-Sidecar-Token": tok} if tok else {}


async def sidecar_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{settings.OCR_SIDECAR_URL.rstrip('/')}/health", headers=_auth_headers())
            return r.status_code == 200
    except Exception:
        return False


async def sidecar_ocr(images: list[bytes], lang: str = "en") -> list[dict]:
    """Run a batch of page images through the PaddleOCR sidecar. Returns one page-result per
    image (same order). Raises on transport/HTTP failure so the caller can fall back."""
    if not images:
        return []
    payload = {"images": [base64.b64encode(im).decode("ascii") for im in images], "lang": lang}
    url = f"{settings.OCR_SIDECAR_URL.rstrip('/')}/ocr"
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(url, json=payload, headers=_auth_headers())
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"OCR sidecar rejected the service token (HTTP {r.status_code}); ensure "
                "OCR_SIDECAR_TOKEN/SIDECAR_AUTH_TOKEN matches the sidecar's configured token."
            )
        r.raise_for_status()
        data = r.json()
    return validate_page_results(data.get("pages") if isinstance(data, dict) else None, len(images))


_GEMINI_OCR_PROMPT = (
    "Transcribe the text from each page image faithfully in reading order. Return STRICT "
    'JSON: {"pages":[{"blocks":[{"kind":"paragraph|heading","text":"..."}]}]}. '
    "Use kind=heading for chapter titles/section headings, paragraph otherwise. Do not "
    "translate, summarize, add commentary, or invent text. Preserve the original language."
)


async def gemini_ocr(
    images: list[bytes], lang: str = "en", *, runtime
) -> list[dict]:
    """Escalate poorly-read pages to Gemini vision. Charges the daily budget (may raise
    BudgetExhausted, which the worker treats as a pause). Returns one page-result per image."""
    from json_repair import repair_json

    if not images:
        return []
    content = [{"type": "text", "text": _GEMINI_OCR_PROMPT}]
    for im in images:
        content.append({"type": "image_url", "image_url": {"url": _data_url(im)}})
    raw = await runtime.call_vision([{"role": "user", "content": content}])
    try:
        data = json.loads(repair_json(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("Gemini OCR returned invalid JSON; no pages were checkpointed.") from exc
    pages = validate_page_results(data.get("pages") if isinstance(data, dict) else None, len(images))
    # Normalize: Gemini reads cleanly, so stamp a high confidence on every block.
    out = []
    for page in pages:
        for b in page.get("blocks", []):
            b.setdefault("kind", "paragraph")
            b["confidence"] = 0.97
        page["mean_confidence"] = 0.97 if page.get("blocks") else 0.0
        out.append(page)
    return out
