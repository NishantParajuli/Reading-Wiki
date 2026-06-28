"""HTTP client for the OmniVoice TTS sidecar (separate GPU deploy on :8078).

Mirrors importer/ocr_client.py: a tiny async httpx wrapper that the durable narration worker
calls one chapter (in fact, one paragraph) at a time. The sidecar holds the model + cached
voice-clone prompts; this module just speaks its contract and degrades gracefully when the
sidecar is down (the worker fails the job with an actionable message).

Contract::

    GET  /health     → {"status":"ok","model_loaded":bool,"voices":[...]}
    GET  /voices     → [{"id","name","language","gender","accent","ready"}]
    POST /synthesize → 24 kHz mono WAV bytes (single passage; for testing/RTF)
    POST /narrate    → Ogg/Opus bytes for a whole chapter (paragraphs concatenated)
"""
from __future__ import annotations

import logging

import httpx

from novelwiki.config.settings import settings

logger = logging.getLogger(__name__)


def _base() -> str:
    return settings.TTS_SIDECAR_URL.rstrip("/")


async def sidecar_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{_base()}/health")
            return r.status_code == 200
    except Exception:
        return False


async def list_voices() -> list[dict]:
    """The sidecar's narrator catalog (id/name/language/gender/accent/ready). Empty list if the
    sidecar is unreachable so callers can render a clear 'TTS offline' state."""
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{_base()}/voices")
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"TTS sidecar /voices unavailable: {e}")
        return []


async def synthesize(
    text: str, voice_id: str, language: str | None = None,
    speed: float | None = None, num_step: int | None = None,
) -> tuple[bytes, float]:
    """Synthesize one passage. Returns (wav_bytes_24k_mono, duration_seconds). Raises on
    transport/HTTP failure so the worker can fail the job cleanly (the sidecar serializes on
    the GPU, so a long passage can legitimately take a while → generous timeout)."""
    payload = {"text": text, "voice_id": voice_id}
    if language:
        payload["language"] = language
    if speed:
        payload["speed"] = speed
    if num_step:
        payload["num_step"] = num_step
    async with httpx.AsyncClient(timeout=600.0) as client:
        r = await client.post(f"{_base()}/synthesize", json=payload)
        r.raise_for_status()
        duration = float(r.headers.get("X-Duration-Seconds", "0") or 0.0)
        return r.content, duration


async def narrate(
    paragraphs: list[str], voice_id: str, language: str | None = None,
    speed: float | None = None, num_step: int | None = None,
    silence_ms: int | None = None, opus_bitrate: str | None = None,
) -> tuple[bytes, float]:
    """Narrate a whole chapter: the sidecar synthesizes each paragraph with the same cached
    clone prompt, concatenates them with silence, and returns Ogg/Opus bytes + duration.
    Long chapters can take minutes on a small GPU, hence the long timeout."""
    payload: dict = {"paragraphs": paragraphs, "voice_id": voice_id}
    if language:
        payload["language"] = language
    if speed:
        payload["speed"] = speed
    if num_step:
        payload["num_step"] = num_step
    if silence_ms is not None:
        payload["silence_ms"] = silence_ms
    if opus_bitrate:
        payload["opus_bitrate"] = opus_bitrate
    async with httpx.AsyncClient(timeout=1800.0) as client:
        r = await client.post(f"{_base()}/narrate", json=payload)
        r.raise_for_status()
        duration = float(r.headers.get("X-Duration-Seconds", "0") or 0.0)
        return r.content, duration
