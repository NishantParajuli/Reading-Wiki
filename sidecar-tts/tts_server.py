"""OmniVoice TTS sidecar — a SEPARATE, GPU-only deployable.

Like the OCR sidecar, this is intentionally NOT part of the main web image (which stays
GPU-free). It loads OmniVoice once, caches a *voice-clone prompt* per curated narrator clip,
and exposes a tiny HTTP surface the web app's ``tts_client`` talks to::

    GET  /health                 → {"status": "ok", "model_loaded": bool, "voices": [...]}  (open)
    GET  /voices                 → [{"id","name","language","gender","accent","ready"}]      (open)
    POST /synthesize             → 24 kHz mono PCM WAV bytes (+ X-Duration-Seconds header)   (token)
        {"text": str, "voice_id": str, "language": str|null, "speed": float|null,
         "num_step": int|null}
    POST /narrate                → Ogg/Opus bytes for a whole chapter (+ X-Duration-Seconds) (token)
        {"paragraphs": [str], "voice_id": str, "language": str|null, "speed": float|null,
         "num_step": int|null, "silence_ms": int|null, "opus_bitrate": str|null}
        Each paragraph is synthesized with the SAME cached clone prompt (stable voice) and
        concatenated with a short silence between them, then encoded to Opus via ffmpeg.

Why voice *cloning* (not voice *design*): OmniVoice's instruct/design path re-rolls the
timbre per call, so a long book would drift between chunks. Cloning with ONE cached
reference prompt per voice, reused for every paragraph/chapter, yields a single consistent
narrator (see k2-fsa/OmniVoice issue #44). We pre-transcribe each clip (``ref_text`` in
voices.json) and load with ``load_asr=False`` so no Whisper is needed at runtime — important
on a 6 GB card.

Run it on the GPU host (default :8078). It should NOT be publicly reachable: deploy it on a
private Docker bridge (the web app reaches it at http://tts:8078) or bound to loopback, and set
SIDECAR_AUTH_TOKEN so /synthesize and /narrate reject anyone without the shared token. The expensive
endpoints fail closed if no token is configured unless SIDECAR_ALLOW_UNAUTHENTICATED=1 is set for
local-only development. Inference is serialized on one lock so a single GPU is never oversubscribed;
request size is capped (TTS_MAX_TEXT_CHARS / TTS_MAX_PARAGRAPHS / TTS_MAX_TOTAL_CHARS).
"""
from __future__ import annotations

import hmac
import io
import json
import logging
import os
import threading
import wave
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tts_server")

app = FastAPI(title="NovelWiki TTS sidecar")


def _env_true(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}

MODEL_NAME = os.environ.get("TTS_MODEL", "k2-fsa/OmniVoice")
DEVICE = os.environ.get("TTS_DEVICE", "cuda:0")
DEFAULT_NUM_STEP = int(os.environ.get("TTS_NUM_STEP", "32"))

# Shared service token. The expensive endpoints (/synthesize, /narrate) require
# `X-Tideglass-Sidecar-Token` (or a bearer Authorization header) matching it. /health and
# /voices stay open (cheap; safe on a private bind). Empty = fail closed unless an explicit
# local-dev opt-out is set. Per-service token wins.
_AUTH_TOKEN = os.environ.get("TTS_SIDECAR_TOKEN") or os.environ.get("SIDECAR_AUTH_TOKEN") or ""
_ALLOW_UNAUTHENTICATED = _env_true("TTS_SIDECAR_ALLOW_UNAUTHENTICATED") or _env_true("SIDECAR_ALLOW_UNAUTHENTICATED")

# Defense-in-depth request caps (env-tunable). A long 8k-word chapter is ~50k chars over ~100
# paragraphs, so these leave ample head-room while blocking abusive payloads.
_MAX_TEXT_CHARS = int(os.environ.get("TTS_MAX_TEXT_CHARS", "20000"))       # one /synthesize passage
_MAX_PARAGRAPHS = int(os.environ.get("TTS_MAX_PARAGRAPHS", "2000"))        # /narrate paragraph count
_MAX_TOTAL_CHARS = int(os.environ.get("TTS_MAX_TOTAL_CHARS", "400000"))    # /narrate total chars


def require_token(
    x_tideglass_sidecar_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Gate the expensive endpoints on the shared token."""
    if not _AUTH_TOKEN:
        if _ALLOW_UNAUTHENTICATED:
            return
        raise HTTPException(status_code=503, detail="Sidecar auth token is not configured.")
    presented = x_tideglass_sidecar_token
    if not presented and authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not presented or not hmac.compare_digest(presented, _AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Missing or invalid sidecar auth token.")

_VOICES_DIR = Path(__file__).parent / "voices"
_VOICES_JSON = _VOICES_DIR / "voices.json"

# Lazily-built singletons. The model is heavy and the HF download can be slow/flaky, so we
# load on first /synthesize (guarded by the lock) rather than at import — /health stays up.
_model = None
_clone_prompts: dict[str, object] = {}          # voice_id → cached voice_clone_prompt
_sr = 24000                                      # overwritten with model.sampling_rate on load
_lock = threading.Lock()                         # one GPU → one inference at a time


class SynthRequest(BaseModel):
    text: str
    voice_id: str
    language: str | None = None
    speed: float | None = None
    num_step: int | None = None


class NarrateRequest(BaseModel):
    paragraphs: list[str]
    voice_id: str
    language: str | None = None
    speed: float | None = None
    num_step: int | None = None
    silence_ms: int | None = None
    opus_bitrate: str | None = None


def _load_voices() -> list[dict]:
    """The curated narrator catalog. Each entry needs a clip file (``file``) sitting next to
    voices.json; a voice with a missing clip is reported as ``ready: false`` and rejected at
    synth time rather than crashing the server."""
    if not _VOICES_JSON.exists():
        logger.warning(f"No voices.json at {_VOICES_JSON}; the sidecar has no narrators.")
        return []
    try:
        raw = json.loads(_VOICES_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Could not parse voices.json: {e}")
        return []
    out = []
    for v in raw.get("voices", []):
        clip = _VOICES_DIR / v.get("file", "")
        out.append({
            "id": v["id"],
            "name": v.get("name", v["id"]),
            "language": v.get("language", "en"),
            "gender": v.get("gender"),
            "accent": v.get("accent"),
            "file": v.get("file"),
            "ref_text": v.get("ref_text", ""),
            "ready": bool(v.get("file")) and clip.exists(),
        })
    return out


def _public_voices() -> list[dict]:
    return [{k: v[k] for k in ("id", "name", "language", "gender", "accent", "ready")}
            for v in _load_voices()]


def _ensure_model():
    """Load OmniVoice once (fp16, ASR off). Caller must hold ``_lock``."""
    global _model, _sr
    if _model is not None:
        return _model
    import torch
    from omnivoice import OmniVoice
    # fp16 on GPU; CPU lacks half-precision kernels for many ops, so fall back to fp32 there.
    dtype = torch.float32 if DEVICE.startswith("cpu") else torch.float16
    logger.info(f"Loading OmniVoice ({MODEL_NAME}) on {DEVICE} ({dtype}, ASR off)…")
    _model = OmniVoice.from_pretrained(
        MODEL_NAME, device_map=DEVICE, dtype=dtype, load_asr=False,
    )
    _sr = int(getattr(_model, "sampling_rate", 24000))
    logger.info(f"OmniVoice ready (sampling_rate={_sr}).")
    return _model


def _clone_prompt_for(voice: dict):
    """Build + cache the voice-clone prompt for one narrator. Caller must hold ``_lock``."""
    vid = voice["id"]
    cached = _clone_prompts.get(vid)
    if cached is not None:
        return cached
    model = _ensure_model()
    ref_audio = str(_VOICES_DIR / voice["file"])
    prompt = model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=voice.get("ref_text") or None)
    _clone_prompts[vid] = prompt
    logger.info(f"Built clone prompt for voice '{vid}'.")
    return prompt


def _to_int16(audio):
    """OmniVoice returns list[np.ndarray] of float32 in [-1, 1]. Take the first stream and
    clamp/convert to a 1-D int16 array."""
    import numpy as np
    arr = audio[0] if isinstance(audio, (list, tuple)) else audio
    arr = np.asarray(arr, dtype=np.float32).reshape(-1)
    return (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16)


def _pcm_to_wav(pcm, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _pcm_to_opus(pcm, sr: int, bitrate: str) -> bytes:
    """Encode 16-bit mono PCM to Ogg/Opus via ffmpeg (piped, no temp files)."""
    import subprocess
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
         "-c:a", "libopus", "-b:a", bitrate, "-f", "ogg", "pipe:1"],
        input=pcm.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg opus encode failed: {proc.stderr.decode('utf-8', 'ignore')[:500]}")
    return proc.stdout


def _norm_lang(lang: str | None) -> str | None:
    """OmniVoice wants a base language id ('en', 'zh', 'ja', …), not a BCP-47 tag. Chapters
    store tags like 'en-GB'/'zh-CN', so strip the region subtag. (Accent comes from the voice
    clone, not this param.) Returns None for blank input → language-agnostic mode."""
    if not lang:
        return None
    base = str(lang).strip().lower().replace("_", "-").split("-")[0]
    return base or None


def _generate(text: str, voice: dict, language: str | None, speed: float | None, num_step: int | None):
    """Run one OmniVoice generation with the voice's cached clone prompt. Caller holds _lock."""
    from omnivoice import OmniVoiceGenerationConfig
    model = _ensure_model()
    prompt = _clone_prompt_for(voice)
    cfg = OmniVoiceGenerationConfig(
        num_step=int(num_step or DEFAULT_NUM_STEP),
        postprocess_output=True,   # trims leading/trailing silence per call
    )
    audio = model.generate(
        text=text,
        language=_norm_lang(language or voice.get("language")),
        voice_clone_prompt=prompt,
        speed=float(speed) if speed else None,
        generation_config=cfg,
    )
    return _to_int16(audio)


def _resolve_voice(voice_id: str) -> dict:
    voice = next((v for v in _load_voices() if v["id"] == voice_id), None)
    if voice is None:
        raise HTTPException(status_code=404, detail=f"Unknown voice '{voice_id}'.")
    if not voice["ready"]:
        raise HTTPException(status_code=503, detail=f"Voice '{voice_id}' has no reference clip on disk.")
    return voice


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None, "voices": _public_voices()}


@app.get("/voices")
def voices():
    return _public_voices()


@app.post("/synthesize")
def synthesize(req: SynthRequest, _: None = Depends(require_token)):
    """One passage → WAV. Handy for testing a voice / measuring RTF; the worker uses /narrate."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text.")
    if len(text) > _MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail=f"Text exceeds {_MAX_TEXT_CHARS}-char cap.")
    voice = _resolve_voice(req.voice_id)
    with _lock:  # one GPU → one inference at a time
        try:
            pcm = _generate(text, voice, req.language, req.speed, req.num_step)
            wav = _pcm_to_wav(pcm, _sr)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Synthesis failed.")
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    duration = len(pcm) / float(_sr) if _sr else 0.0
    return Response(content=wav, media_type="audio/wav",
                    headers={"X-Duration-Seconds": f"{duration:.3f}", "X-Sample-Rate": str(_sr)})


@app.post("/narrate")
def narrate(req: NarrateRequest, _: None = Depends(require_token)):
    """A whole chapter: synthesize each paragraph with the SAME cached clone prompt (stable
    narrator), concatenate with a short silence between them, encode Opus. Returns Ogg/Opus."""
    import numpy as np
    paras = [p.strip() for p in (req.paragraphs or []) if p and p.strip()]
    if not paras:
        raise HTTPException(status_code=400, detail="No paragraphs to narrate.")
    if len(paras) > _MAX_PARAGRAPHS:
        raise HTTPException(status_code=413, detail=f"Too many paragraphs: {len(paras)} > {_MAX_PARAGRAPHS}.")
    total_chars = sum(len(p) for p in paras)
    if total_chars > _MAX_TOTAL_CHARS:
        raise HTTPException(status_code=413, detail=f"Text exceeds {_MAX_TOTAL_CHARS}-char cap.")
    voice = _resolve_voice(req.voice_id)
    silence_ms = max(0, int(req.silence_ms if req.silence_ms is not None else 350))
    bitrate = req.opus_bitrate or "48k"

    with _lock:  # hold the GPU for the whole chapter so the voice/timbre is consistent
        try:
            gap = np.zeros(int(_sr * silence_ms / 1000), dtype=np.int16)
            chunks = []
            for i, para in enumerate(paras):
                chunks.append(_generate(para, voice, req.language, req.speed, req.num_step))
                if silence_ms and i < len(paras) - 1:
                    chunks.append(gap)
            pcm = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            opus = _pcm_to_opus(pcm, _sr, bitrate)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Narration failed.")
            raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    duration = len(pcm) / float(_sr) if _sr else 0.0
    return Response(content=opus, media_type="audio/ogg",
                    headers={"X-Duration-Seconds": f"{duration:.3f}", "X-Sample-Rate": str(_sr)})


if __name__ == "__main__":
    import uvicorn
    # Loopback by default (safe under host networking); compose overrides UVICORN_HOST=0.0.0.0 so
    # the web app can reach it over the private bridge without publishing the port to the host.
    host = os.environ.get("UVICORN_HOST", "127.0.0.1")
    port = int(os.environ.get("UVICORN_PORT", "8078"))
    uvicorn.run(app, host=host, port=port)
