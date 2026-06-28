"""Audiobook TTS: durable narration jobs + the OmniVoice sidecar client.

The heavy model lives in a separate GPU sidecar (see ``sidecar-tts/``); this package is the
web-side half — the HTTP client, text normalization, and the durable, resumable worker that
turns chapters into cached Opus audio one chapter at a time.
"""
