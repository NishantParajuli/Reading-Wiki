"""HTTP client for the OmniVoice TTS sidecar (separate GPU deploy on :8078).

Mirrors importer/ocr_client.py: a tiny async httpx wrapper that the durable narration worker
calls once per chapter. The sidecar holds the model + cached voice-clone prompts and
synthesizes each paragraph separately; this module just speaks its contract and degrades
gracefully when the sidecar is down (the worker fails the job with an actionable message).

Contract::

    GET  /health     → {"status":"ok","model_loaded":bool,"voices":[...]}
    GET  /voices     → [{"id","name","language","gender","accent","ready"}]
    POST /synthesize → 24 kHz mono WAV bytes (single passage; for testing/RTF)
    POST /narrate    → Ogg/Opus bytes, optionally multipart timing JSON + Opus
"""
from __future__ import annotations

from email.parser import BytesParser
from email.policy import default
import json
import logging

import httpx

from novelwiki.platform.config import settings

logger = logging.getLogger(__name__)


def _base() -> str:
    return settings.TTS_SIDECAR_URL.rstrip("/")


def _auth_headers() -> dict[str, str]:
    """Shared service token the sidecar requires on /synthesize + /narrate (empty → no header)."""
    tok = settings.tts_sidecar_token
    return {"X-Tideglass-Sidecar-Token": tok} if tok else {}


def _raise_if_unauthorized(status_code: int) -> None:
    if status_code in (401, 403):
        raise RuntimeError(
            f"TTS sidecar rejected the service token (HTTP {status_code}); ensure "
            "TTS_SIDECAR_TOKEN/SIDECAR_AUTH_TOKEN matches the sidecar's configured token."
        )


def _parse_timed_narration(
    content: bytes, content_type: str, paragraph_count: int,
) -> tuple[bytes, dict]:
    message = BytesParser(policy=default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii")
        + content
    )
    audio = None
    manifest = None
    for part in message.iter_parts():
        payload_bytes = part.get_payload(decode=True)
        if part.get_content_type() == "audio/ogg":
            audio = payload_bytes
        elif part.get_content_type() == "application/json":
            manifest = json.loads(payload_bytes.decode("utf-8"))
    durations = manifest.get("paragraph_durations_ms") if isinstance(manifest, dict) else None
    valid_manifest = (
        isinstance(manifest, dict)
        and manifest.get("version") == 1
        and type(manifest.get("duration_ms")) is int
        and manifest["duration_ms"] > 0
        and type(manifest.get("silence_ms")) is int
        and manifest["silence_ms"] >= 0
        and isinstance(durations, list)
        and len(durations) == paragraph_count
        and all(type(value) is int and value >= 0 for value in durations)
    )
    if audio is None or not valid_manifest:
        raise RuntimeError("TTS sidecar returned an invalid timed narration response.")
    return audio, manifest


async def sidecar_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{_base()}/health", headers=_auth_headers())
            return r.status_code == 200
    except Exception:
        return False


async def list_voices() -> list[dict]:
    """The sidecar's narrator catalog (id/name/language/gender/accent/ready). Empty list if the
    sidecar is unreachable so callers can render a clear 'TTS offline' state."""
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(f"{_base()}/voices", headers=_auth_headers())
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
        r = await client.post(f"{_base()}/synthesize", json=payload, headers=_auth_headers())
        _raise_if_unauthorized(r.status_code)
        r.raise_for_status()
        duration = float(r.headers.get("X-Duration-Seconds", "0") or 0.0)
        return r.content, duration


async def narrate(
    paragraphs: list[str], voice_id: str, language: str | None = None,
    speed: float | None = None, num_step: int | None = None,
    silence_ms: int | None = None, opus_bitrate: str | None = None,
) -> tuple[bytes, float, dict | None]:
    """Narrate a whole chapter: the sidecar synthesizes each paragraph with the same cached
    clone prompt, concatenates them with silence, and returns Ogg/Opus bytes, duration, and
    actual paragraph durations. An older sidecar's audio-only response remains accepted and
    returns ``None`` timing data during rolling deploys. Long chapters can take minutes on a
    small GPU, hence the long timeout."""
    payload: dict = {
        "paragraphs": paragraphs,
        "voice_id": voice_id,
        "include_timing_manifest": True,
    }
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
        r = await client.post(f"{_base()}/narrate", json=payload, headers=_auth_headers())
        _raise_if_unauthorized(r.status_code)
        r.raise_for_status()
        duration = float(r.headers.get("X-Duration-Seconds", "0") or 0.0)
        content_type = r.headers.get("content-type", "")
        if not content_type.lower().startswith("multipart/"):
            return r.content, duration, None
        audio, manifest = _parse_timed_narration(
            r.content, content_type, len(paragraphs)
        )
        return audio, duration, manifest
