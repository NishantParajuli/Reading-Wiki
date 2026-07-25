from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
SIDECAR_ROOT = ROOT / "sidecar-tts"
if str(SIDECAR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIDECAR_ROOT))

import tts_server  # noqa: E402

from novelwiki.modules.narration.adapters.outbound import sidecar  # noqa: E402


def test_sidecar_returns_actual_duration_per_generated_paragraph(monkeypatch):
    monkeypatch.setattr(tts_server, "_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(
        tts_server,
        "_resolve_voice",
        lambda voice_id: {
            "id": voice_id,
            "ready": True,
            "language": "en",
            "file": "narrator.wav",
        },
    )
    samples = {"short": 2400, "long": 7200}
    monkeypatch.setattr(
        tts_server,
        "_generate",
        lambda text, *_: np.zeros(samples[text], dtype=np.int16),
    )
    monkeypatch.setattr(tts_server, "_pcm_to_opus", lambda *_: b"OggS-timed-audio")

    response = TestClient(tts_server.app).post(
        "/narrate",
        headers={"X-Tideglass-Sidecar-Token": "test-token"},
        json={
            "paragraphs": ["short", "long"],
            "voice_id": "narrator",
            "silence_ms": 350,
            "include_timing_manifest": True,
        },
    )

    assert response.status_code == 200
    audio, manifest = sidecar._parse_timed_narration(
        response.content, response.headers["content-type"], paragraph_count=2,
    )
    assert audio == b"OggS-timed-audio"
    assert manifest == {
        "version": 1,
        "duration_ms": 750,
        "silence_ms": 350,
        "paragraph_durations_ms": [100, 300],
    }


@pytest.mark.asyncio
async def test_web_client_keeps_legacy_audio_only_sidecar_compatible(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        content = b"legacy-ogg"
        headers = {
            "content-type": "audio/ogg",
            "X-Duration-Seconds": "12.5",
        }

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers):
            captured.update(json)
            return Response()

    monkeypatch.setattr(sidecar.httpx, "AsyncClient", Client)

    audio, duration, manifest = await sidecar.narrate(["Hello."], "narrator")

    assert captured["include_timing_manifest"] is True
    assert (audio, duration, manifest) == (b"legacy-ogg", 12.5, None)
