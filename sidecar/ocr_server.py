"""PaddleOCR OCR sidecar — a SEPARATE, GPU-only deployable.

This is intentionally NOT part of the main web image (which stays GPU-free). It exposes a
tiny HTTP surface the importer's ``ocr_client`` talks to:

    GET  /health           → {"status": "ok"}
    POST /ocr  {"images": [<base64 png>, ...], "lang": "en|ch|..."}
        → {"pages": [{"blocks": [{"kind","text","confidence","bbox"}], "mean_confidence": float}]}

Run it on the GPU host (default :8077). With the web container on `network_mode: host`, the
importer reaches it at http://localhost:8077 for free. One model is loaded per language and
cached; requests are processed serially so a single 6 GB GPU is never oversubscribed.
"""
from __future__ import annotations

import base64
import io
import logging
import threading

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ocr_server")

app = FastAPI(title="NovelWiki OCR sidecar")

# PaddleOCR lang codes differ from ours: map the languages we send to Paddle's keys.
_LANG_MAP = {"en": "en", "zh": "ch", "ja": "japan", "ko": "korean"}
_models: dict[str, object] = {}
_model_lock = threading.Lock()


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
def ocr(req: OcrRequest):
    model = _get_model(req.lang)
    pages = []
    # Serial on purpose: one GPU, so we never run two inferences concurrently.
    with _model_lock:
        for b64 in req.images:
            try:
                data = base64.b64decode(b64)
                pages.append(_ocr_image(model, data))
            except Exception as e:
                logger.warning(f"OCR failed for a page: {e}")
                pages.append({"blocks": [], "mean_confidence": 0.0})
    return {"pages": pages}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8077)
