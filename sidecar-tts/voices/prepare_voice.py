#!/usr/bin/env python3
"""Helper to prepare a narrator reference clip for the TTS sidecar.

Usage:
    python3 prepare_voice.py INPUT_AUDIO OUTPUT.wav --text "exact transcription of the clip"

It resamples/downmixes INPUT_AUDIO to 24 kHz mono 16-bit WAV (OmniVoice's native format),
trims it to a sane length, and prints the voices.json snippet to paste in. Keep clips 3-10s.

Requires `soundfile` and `numpy` (and `librosa` for resampling if the input isn't already
24 kHz). This is an operator convenience, not part of the running sidecar.
"""
from __future__ import annotations

import argparse
import json
import sys

TARGET_SR = 24000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--text", required=True, help="EXACT transcription of the clip (goes in ref_text).")
    ap.add_argument("--max-seconds", type=float, default=10.0)
    args = ap.parse_args()

    try:
        import numpy as np
        import soundfile as sf
    except Exception as e:  # pragma: no cover - operator tool
        print(f"Missing deps (pip install soundfile numpy librosa): {e}", file=sys.stderr)
        return 2

    audio, sr = sf.read(args.input, dtype="float32")
    if audio.ndim > 1:                       # downmix to mono
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        try:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)
        except Exception as e:
            print(f"Resampling needs librosa (pip install librosa): {e}", file=sys.stderr)
            return 2
    audio = audio[: int(args.max_seconds * TARGET_SR)]
    sf.write(args.output, audio, TARGET_SR, subtype="PCM_16")

    secs = len(audio) / TARGET_SR
    print(f"Wrote {args.output} — {secs:.1f}s, {TARGET_SR} Hz mono.")
    print("voices.json entry:")
    print(json.dumps({
        "id": "<id>", "name": "<Name>", "language": "en",
        "gender": "<female|male>", "accent": "<US|UK|...>",
        "file": args.output.split("/")[-1], "ref_text": args.text,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
