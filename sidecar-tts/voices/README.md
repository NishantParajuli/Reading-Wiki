# Narrator voices

The TTS sidecar narrates books by **voice cloning**: for each voice it builds one cached
clone prompt from a short reference clip and reuses it for every paragraph and chapter, so a
whole book gets a single consistent narrator (OmniVoice's "voice design" path drifts between
chunks and is deliberately not used).

## Adding a voice

Each entry in `voices.json` needs two things sitting next to it in this folder:

1. **A reference clip** at `file` — 3–10 seconds, **24 kHz mono 16-bit WAV**, clean speech in
   the voice's language. Longer clips slow inference and can *degrade* cloning quality.
2. **`ref_text`** — the **exact** transcription of that clip. This is **required**: the sidecar
   loads with `load_asr=False` (no Whisper) to save VRAM on small GPUs, so it never transcribes
   the clip for you. A clip with an empty `ref_text` will fail.

A voice whose clip file is missing is reported as `ready: false` by `/voices` and `/health`,
and rejected at synth time — the rest of the sidecar keeps working.

## Licensing

Use **public-domain / CC0** audio only (the reference voice is redistributed inside the
container image). [LibriVox](https://librivox.org) recordings are public domain and a good
source; pick a clean 3–10s sentence and transcribe it exactly.

**Do not** clone a real person's voice without their consent.

## Convenience

`prepare_voice.py` resamples/downmixes any input clip to the required 24 kHz mono WAV, trims
it, and prints the `voices.json` snippet:

```bash
python3 prepare_voice.py raw_clip.mp3 aria.wav --text "the exact words spoken in the clip"
```

The five voices shipped in `voices.json` (`aria`, `james`, `mei`, `lin`, `haru`) are
placeholders — drop in clips + transcriptions to activate them, or edit the catalog.
