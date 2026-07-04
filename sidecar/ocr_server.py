"""PaddleOCR OCR sidecar — a SEPARATE, GPU-only deployable.

This is intentionally NOT part of the main web image (which stays GPU-free). It exposes a
tiny HTTP surface the importer's ``ocr_client`` talks to:

    GET  /health           → {"status": "ok"}                         (unauthenticated)
    POST /ocr  {"images": [<base64 png>, ...], "lang": "en|ch|..."}   (requires service token)
        → {"pages": [{"blocks": [{"kind","text","confidence","bbox"}], "mean_confidence": float}]}

Run it on the GPU host (default :8077). It should NOT be publicly reachable:
deploy it on a private Docker bridge (the web app reaches it at http://ocr:8077) or bound to
loopback, and set SIDECAR_AUTH_TOKEN so /ocr rejects anyone without the shared token. The expensive
endpoint fails closed if no token is configured unless SIDECAR_ALLOW_UNAUTHENTICATED=1 is set for
local-only development. One model is loaded per language and cached; requests are processed serially
so a single 6 GB GPU is never oversubscribed. Request size is capped (OCR_MAX_IMAGES /
OCR_MAX_IMAGE_BYTES / OCR_MAX_TOTAL_BYTES).
"""
from __future__ import annotations

import base64
import hmac
import io
import logging
import os
import threading

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ocr_server")

app = FastAPI(title="NovelWiki OCR sidecar")


def _env_true(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}

# Shared service token. /ocr requires `X-Tideglass-Sidecar-Token` (or a bearer Authorization
# header) matching it, so a reachable port can't be driven by anyone but the web app. Empty =
# fail closed unless an explicit local-dev opt-out is set. A per-service token wins.
_AUTH_TOKEN = os.environ.get("OCR_SIDECAR_TOKEN") or os.environ.get("SIDECAR_AUTH_TOKEN") or ""
_ALLOW_UNAUTHENTICATED = _env_true("OCR_SIDECAR_ALLOW_UNAUTHENTICATED") or _env_true("SIDECAR_ALLOW_UNAUTHENTICATED")

# Defense-in-depth request caps (env-tunable). The web importer batches SIDECAR_BATCH=4 pages
# per call, so 16 images leaves head-room; a rendered page is well under the per-image byte cap.
_MAX_IMAGES = int(os.environ.get("OCR_MAX_IMAGES", "16"))
_MAX_IMAGE_BYTES = int(os.environ.get("OCR_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))
_MAX_TOTAL_BYTES = int(os.environ.get("OCR_MAX_TOTAL_BYTES", str(64 * 1024 * 1024)))

# PaddleOCR lang codes differ from ours: map the languages we send to Paddle's keys.
_LANG_MAP = {"en": "en", "zh": "ch", "ja": "japan", "ko": "korean"}
_models: dict[str, object] = {}
_model_lock = threading.Lock()


def require_token(
    x_tideglass_sidecar_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Gate the expensive endpoint on the shared token."""
    if not _AUTH_TOKEN:
        if _ALLOW_UNAUTHENTICATED:
            return
        raise HTTPException(status_code=503, detail="Sidecar auth token is not configured.")
    presented = x_tideglass_sidecar_token
    if not presented and authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not presented or not hmac.compare_digest(presented, _AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Missing or invalid sidecar auth token.")


class OcrRequest(BaseModel):
    images: list[str]            # base64-encoded page images (PNG)
    lang: str = "en"


def _get_model(lang: str):
    """Lazily build and cache one PaddleOCR instance per language (thread-safe)."""
    key = _LANG_MAP.get((lang or "en")[:2], "en")
    with _model_lock:
        if key not in _models:
            from paddleocr import PaddleOCR
            logger.info(f"Loading PaddleOCR model for lang={key} …")
            _models[key] = PaddleOCR(use_angle_cls=True, lang=key, show_log=False)
        return _models[key]


def _ocr_image(model, data: bytes) -> dict:
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.array(img)
    result = model.ocr(arr, cls=True)
    # PaddleOCR returns [[ [bbox, (text, confidence)], ... ]] (one list per image).
    lines = result[0] if result and result[0] else []
    blocks, confs = [], []
    for line in lines:
        try:
            bbox, (text, conf) = line[0], line[1]
        except (ValueError, TypeError, IndexError):
            continue
        text = (text or "").strip()
        if not text:
            continue
        confs.append(float(conf))
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        blocks.append({
            "kind": "paragraph",
            "text": text,
            "confidence": round(float(conf), 4),
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
        })
    mean_conf = round(sum(confs) / len(confs), 4) if confs else 0.0
    return {"blocks": blocks, "mean_confidence": mean_conf}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ocr")
def ocr(req: OcrRequest, _: None = Depends(require_token)):
    if len(req.images) > _MAX_IMAGES:
        raise HTTPException(status_code=413, detail=f"Too many images: {len(req.images)} > {_MAX_IMAGES}.")
    model = _get_model(req.lang)
    pages = []
    total = 0
    # Serial on purpose: one GPU, so we never run two inferences concurrently.
    with _model_lock:
        for b64 in req.images:
            try:
                data = base64.b64decode(b64)
            except Exception as e:
                # Malformed page → skip it (resilient), but don't fail the whole batch.
                logger.warning(f"OCR could not decode a page: {e}")
                pages.append({"blocks": [], "mean_confidence": 0.0})
                continue
            if len(data) > _MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail=f"Image exceeds {_MAX_IMAGE_BYTES}-byte cap.")
            total += len(data)
            if total > _MAX_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail=f"Request exceeds {_MAX_TOTAL_BYTES}-byte cap.")
            try:
                pages.append(_ocr_image(model, data))
            except Exception as e:
                logger.warning(f"OCR failed for a page: {e}")
                pages.append({"blocks": [], "mean_confidence": 0.0})
    return {"pages": pages}


if __name__ == "__main__":
    import uvicorn
    # Loopback by default (safe under host networking); compose overrides UVICORN_HOST=0.0.0.0 so
    # the web app can reach it over the private bridge without publishing the port to the host.
    host = os.environ.get("UVICORN_HOST", "127.0.0.1")
    port = int(os.environ.get("UVICORN_PORT", "8077"))
    uvicorn.run(app, host=host, port=port)
