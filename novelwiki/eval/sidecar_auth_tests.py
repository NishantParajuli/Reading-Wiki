"""Batch 6 regression: sidecar network isolation + service auth (report H4).

Covers four guarantees:

  1. The expensive sidecar endpoints (OCR /ocr, TTS /synthesize, /narrate) reject callers
     without the shared service token, fail closed if no token is configured, and accept a valid one.
  2. The sidecars cap request size (image count / decoded bytes, paragraph count / total chars)
     so a reachable port can't be turned into a cheap resource-exhaustion lever.
  3. The web clients attach the token header and surface a clear error on 401/403.
  4. docker-compose.yml no longer relies on host networking and never publishes the sidecar
     ports (8077/8078) to the host — they live only on the private bridge.

The sidecars are standalone modules under ``sidecar/`` and ``sidecar-tts/`` (GPU-only deploys,
not part of the web package); their heavy deps (paddleocr/torch/omnivoice) are imported lazily,
so the modules import fine here and we mock the model calls.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "sidecar", _ROOT / "sidecar-tts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ocr_server            # noqa: E402  (sidecar/ocr_server.py)
import tts_server            # noqa: E402  (sidecar-tts/tts_server.py)

from novelwiki.config.settings import settings          # noqa: E402
from novelwiki.importer import ocr_client               # noqa: E402
from novelwiki.tts import tts_client                    # noqa: E402

TOKEN = "s3cr3t-sidecar-token"
_HDR = "X-Tideglass-Sidecar-Token"


def _b64_image(data: bytes = b"not-a-real-image") -> str:
    return base64.b64encode(data).decode("ascii")


# ─────────────────────────── OCR sidecar auth ───────────────────────────

def test_ocr_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", TOKEN)
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image()], "lang": "en"})
    assert r.status_code == 401


def test_ocr_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", TOKEN)
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image()], "lang": "en"}, headers={_HDR: "nope"})
    assert r.status_code == 401


def test_ocr_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(ocr_server, "_get_model", lambda lang: object())
    monkeypatch.setattr(ocr_server, "_ocr_image", lambda model, data: {"blocks": [], "mean_confidence": 0.0})
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image()], "lang": "en"}, headers={_HDR: TOKEN})
    assert r.status_code == 200
    assert r.json()["pages"] == [{"blocks": [], "mean_confidence": 0.0}]


def test_ocr_accepts_bearer_token(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(ocr_server, "_get_model", lambda lang: object())
    monkeypatch.setattr(ocr_server, "_ocr_image", lambda model, data: {"blocks": [], "mean_confidence": 0.0})
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image()], "lang": "en"},
                    headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200


def test_ocr_fails_closed_when_no_token_configured(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", "")
    monkeypatch.setattr(ocr_server, "_ALLOW_UNAUTHENTICATED", False)
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image()], "lang": "en"})
    assert r.status_code == 503


def test_ocr_dev_opt_out_allows_no_token(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", "")
    monkeypatch.setattr(ocr_server, "_ALLOW_UNAUTHENTICATED", True)
    monkeypatch.setattr(ocr_server, "_get_model", lambda lang: object())
    monkeypatch.setattr(ocr_server, "_ocr_image", lambda model, data: {"blocks": [], "mean_confidence": 0.0})
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image()], "lang": "en"})
    assert r.status_code == 200


def test_ocr_health_is_open(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", TOKEN)
    client = TestClient(ocr_server.app)
    assert client.get("/health").status_code == 200


# ─────────────────────────── OCR size caps ───────────────────────────

def test_ocr_rejects_too_many_images(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(ocr_server, "_MAX_IMAGES", 2)
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image()] * 3, "lang": "en"}, headers={_HDR: TOKEN})
    assert r.status_code == 413


def test_ocr_rejects_oversized_image(monkeypatch):
    monkeypatch.setattr(ocr_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(ocr_server, "_MAX_IMAGE_BYTES", 8)
    monkeypatch.setattr(ocr_server, "_get_model", lambda lang: object())
    monkeypatch.setattr(ocr_server, "_ocr_image", lambda model, data: {"blocks": [], "mean_confidence": 0.0})
    client = TestClient(ocr_server.app)
    r = client.post("/ocr", json={"images": [_b64_image(b"x" * 64)], "lang": "en"}, headers={_HDR: TOKEN})
    assert r.status_code == 413


# ─────────────────────────── TTS sidecar auth ───────────────────────────

def test_tts_synthesize_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    client = TestClient(tts_server.app)
    r = client.post("/synthesize", json={"text": "hi", "voice_id": "narrator"})
    assert r.status_code == 401


def test_tts_narrate_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    client = TestClient(tts_server.app)
    r = client.post("/narrate", json={"paragraphs": ["hi"], "voice_id": "narrator"})
    assert r.status_code == 401


def test_tts_narrate_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    client = TestClient(tts_server.app)
    r = client.post("/narrate", json={"paragraphs": ["hi"], "voice_id": "narrator"}, headers={_HDR: "nope"})
    assert r.status_code == 401


def test_tts_synthesize_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(tts_server, "_resolve_voice",
                        lambda vid: {"id": vid, "ready": True, "language": "en", "file": "narrator.wav"})
    monkeypatch.setattr(tts_server, "_generate",
                        lambda text, voice, language, speed, num_step: np.zeros(2400, dtype=np.int16))
    client = TestClient(tts_server.app)
    r = client.post("/synthesize", json={"text": "hello", "voice_id": "narrator"}, headers={_HDR: TOKEN})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"


def test_tts_fails_closed_when_no_token_configured(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", "")
    monkeypatch.setattr(tts_server, "_ALLOW_UNAUTHENTICATED", False)
    client = TestClient(tts_server.app)
    r = client.post("/synthesize", json={"text": "hi", "voice_id": "narrator"})
    assert r.status_code == 503


def test_tts_dev_opt_out_allows_no_token(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", "")
    monkeypatch.setattr(tts_server, "_ALLOW_UNAUTHENTICATED", True)
    monkeypatch.setattr(tts_server, "_resolve_voice",
                        lambda vid: {"id": vid, "ready": True, "language": "en", "file": "narrator.wav"})
    monkeypatch.setattr(tts_server, "_generate",
                        lambda text, voice, language, speed, num_step: np.zeros(2400, dtype=np.int16))
    client = TestClient(tts_server.app)
    r = client.post("/synthesize", json={"text": "hello", "voice_id": "narrator"})
    assert r.status_code == 200


def test_tts_voices_is_open(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    client = TestClient(tts_server.app)
    assert client.get("/voices").status_code == 200


# ─────────────────────────── TTS size caps ───────────────────────────

def test_tts_narrate_rejects_too_many_paragraphs(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(tts_server, "_MAX_PARAGRAPHS", 2)
    client = TestClient(tts_server.app)
    r = client.post("/narrate", json={"paragraphs": ["a", "b", "c"], "voice_id": "narrator"},
                    headers={_HDR: TOKEN})
    assert r.status_code == 413


def test_tts_narrate_rejects_too_many_chars(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(tts_server, "_MAX_TOTAL_CHARS", 10)
    client = TestClient(tts_server.app)
    r = client.post("/narrate", json={"paragraphs": ["x" * 50], "voice_id": "narrator"},
                    headers={_HDR: TOKEN})
    assert r.status_code == 413


def test_tts_synthesize_rejects_too_long_text(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", TOKEN)
    monkeypatch.setattr(tts_server, "_MAX_TEXT_CHARS", 5)
    client = TestClient(tts_server.app)
    r = client.post("/synthesize", json={"text": "x" * 50, "voice_id": "narrator"}, headers={_HDR: TOKEN})
    assert r.status_code == 413


# ─────────────────────────── Web client token plumbing ───────────────────────────

def test_client_auth_headers_reflect_settings(monkeypatch):
    monkeypatch.setattr(settings, "SIDECAR_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "OCR_SIDECAR_TOKEN", "")
    monkeypatch.setattr(settings, "TTS_SIDECAR_TOKEN", "")
    assert ocr_client._auth_headers() == {}
    assert tts_client._auth_headers() == {}

    monkeypatch.setattr(settings, "SIDECAR_AUTH_TOKEN", TOKEN)
    assert ocr_client._auth_headers() == {_HDR: TOKEN}
    assert tts_client._auth_headers() == {_HDR: TOKEN}

    # Per-service token overrides the shared one.
    monkeypatch.setattr(settings, "OCR_SIDECAR_TOKEN", "ocr-only")
    assert ocr_client._auth_headers() == {_HDR: "ocr-only"}
    assert tts_client._auth_headers() == {_HDR: TOKEN}


class _FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = {}
        self.content = b""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            req = httpx.Request("POST", "http://sidecar/")
            raise httpx.HTTPStatusError("error", request=req,
                                        response=httpx.Response(self.status_code, request=req))


def _fake_async_client(status: int, capture: list, json_data=None):
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None, **k):
            capture.append(("GET", url, headers or {}))
            return _FakeResp(status, json_data)

        async def post(self, url, headers=None, json=None, **k):
            capture.append(("POST", url, headers or {}))
            return _FakeResp(status, json_data)

    return _Client


@pytest.mark.asyncio
async def test_ocr_client_sends_token(monkeypatch):
    monkeypatch.setattr(settings, "OCR_SIDECAR_TOKEN", "")
    monkeypatch.setattr(settings, "SIDECAR_AUTH_TOKEN", TOKEN)
    cap: list = []
    monkeypatch.setattr(ocr_client.httpx, "AsyncClient", _fake_async_client(200, cap, {"pages": []}))
    await ocr_client.sidecar_ocr([b"img"], "en")
    assert cap and cap[-1][2].get(_HDR) == TOKEN


@pytest.mark.asyncio
async def test_ocr_client_raises_on_401(monkeypatch):
    monkeypatch.setattr(settings, "SIDECAR_AUTH_TOKEN", TOKEN)
    cap: list = []
    monkeypatch.setattr(ocr_client.httpx, "AsyncClient", _fake_async_client(401, cap, {"detail": "no"}))
    with pytest.raises(RuntimeError, match="rejected the service token"):
        await ocr_client.sidecar_ocr([b"img"], "en")


@pytest.mark.asyncio
async def test_tts_client_sends_token_and_raises_on_403(monkeypatch):
    monkeypatch.setattr(settings, "TTS_SIDECAR_TOKEN", "")
    monkeypatch.setattr(settings, "SIDECAR_AUTH_TOKEN", TOKEN)
    cap: list = []
    monkeypatch.setattr(tts_client.httpx, "AsyncClient", _fake_async_client(200, cap))
    await tts_client.narrate(["hi"], "narrator")
    assert cap and cap[-1][2].get(_HDR) == TOKEN

    monkeypatch.setattr(tts_client.httpx, "AsyncClient", _fake_async_client(403, [], {"detail": "no"}))
    with pytest.raises(RuntimeError, match="rejected the service token"):
        await tts_client.narrate(["hi"], "narrator")


# ─────────────────────────── Compose network isolation ───────────────────────────

def _compose() -> dict:
    return yaml.safe_load((_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_compose_drops_host_networking():
    services = _compose()["services"]
    for name, svc in services.items():
        assert svc.get("network_mode") != "host", f"{name} must not use host networking"


def test_compose_does_not_publish_sidecar_ports():
    services = _compose()["services"]
    for name in ("ocr", "tts"):
        assert "ports" not in services[name], f"{name} must not publish ports to the host"


def test_compose_web_port_is_loopback_only():
    web = _compose()["services"]["web"]
    for mapping in web.get("ports", []):
        assert str(mapping).startswith("127.0.0.1:"), f"web port {mapping} must bind loopback only"


def test_compose_sidecars_share_private_network():
    services = _compose()["services"]
    for name in ("web", "ocr", "tts"):
        assert "tideglass" in (services[name].get("networks") or []), f"{name} must be on the private bridge"


def test_compose_passes_per_service_tokens_to_sidecars():
    services = _compose()["services"]
    assert services["web"]["environment"]["SIDECAR_AUTH_TOKEN"] == "${SIDECAR_AUTH_TOKEN:-}"
    assert services["web"]["environment"]["OCR_SIDECAR_TOKEN"] == "${OCR_SIDECAR_TOKEN:-}"
    assert services["web"]["environment"]["TTS_SIDECAR_TOKEN"] == "${TTS_SIDECAR_TOKEN:-}"
    assert services["ocr"]["environment"]["SIDECAR_AUTH_TOKEN"] == "${SIDECAR_AUTH_TOKEN:-}"
    assert services["ocr"]["environment"]["OCR_SIDECAR_TOKEN"] == "${OCR_SIDECAR_TOKEN:-}"
    assert services["tts"]["environment"]["SIDECAR_AUTH_TOKEN"] == "${SIDECAR_AUTH_TOKEN:-}"
    assert services["tts"]["environment"]["TTS_SIDECAR_TOKEN"] == "${TTS_SIDECAR_TOKEN:-}"


def test_compose_dev_unauthenticated_sidecar_mode_is_off_by_default():
    services = _compose()["services"]
    assert services["ocr"]["environment"]["SIDECAR_ALLOW_UNAUTHENTICATED"] == "${SIDECAR_ALLOW_UNAUTHENTICATED:-0}"
    assert services["tts"]["environment"]["SIDECAR_ALLOW_UNAUTHENTICATED"] == "${SIDECAR_ALLOW_UNAUTHENTICATED:-0}"
