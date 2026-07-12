# Pipeline: audiobook narration (TTS)

> How a chapter becomes cached Opus audio in a consistent cloned voice, and how the
> reader streams it. Module reference: [../modules/narration.md](../modules/narration.md).

## Topology

The web image stays GPU-free. Synthesis runs on the **OmniVoice sidecar**
(`sidecar-tts/`, port `:8078`, Docker profile `tts`), which holds the model and cached
voice-clone prompts. The durable **TTS worker** inside the web process feeds it one
chapter at a time and caches results. Sidecar endpoints require the shared service token
(`X-Tideglass-Sidecar-Token`); they fail closed without one. Voices are cloned from
fixed reference clips in `sidecar-tts/voices/` (one clip per narrator ⇒ one consistent
voice across a whole book; see that folder's README — consented/public-domain audio
only).

## Requesting audio

- **One chapter** — `POST /api/novels/{id}/chapter/{n}/audio` (voice optional; default
  `TTS_DEFAULT_VOICE`). If the exact target — `(novel, chapter, voice,
  content_version, base-or-this-user)` — is already cached: returned immediately,
  **no charge**. Else: dedupe onto an identical active job, or create a
  `scope='chapter'` `tts_jobs` row (quota `check_available` first).
- **Whole book** — `POST /api/novels/{id}/audiobook`: candidate prose chapters
  (non-chapter `kind`s and already-narrated ones skipped), hard-capped at
  `TTS_MAX_BATCH_CHAPTERS` (100), one active book job per (novel, voice); the explicit
  chapter list is stored in `options.chapters`; cancellable mid-run keeping finished
  chapters.
- The reader's transport UI polls `GET …/audio/status`, then streams
  `GET …/chapter/{n}/audio.opus` (access-controlled `FileResponse`; HTTP **Range**
  supported, so scrubbing works).

## The worker, per chapter

1. **Skip if cached** (idempotent — restart-safe).
2. **Resolve text via Reading** (`resolve_narration_text`) — **overlay-aware**: a reader
   with a personal edited translation hears *their* text (audio row stamped with their
   `user_id`); everyone else shares the base row (`user_id IS NULL`).
3. **Text prep** (`domain/textprep.py`) — markup stripped, paragraphs split, numbers/
   abbreviations normalized, optional spoken intro "Chapter N. Title."
   (`TTS_TITLE_INTRO`).
4. **Sidecar `narrate`** — per-paragraph synthesis with the same cached voice prompt,
   `TTS_PARA_SILENCE_MS` (350 ms) gaps, `TTS_NUM_STEP` (32) diffusion steps,
   `TTS_SPEED`.
5. **Encode + store** — ffmpeg → Opus (`TTS_OPUS_BITRATE` 48k) under `AUDIO_DIR`
   (outside the public asset mount), upsert `chapter_audio` (partial-unique per
   base/per-user target), duration + bytes recorded.
6. **Meter** — 1 × `tts_chapters` **only on actual generation** (default 200/month).

Job mechanics: `queued → generating → done|failed|canceled`; startup requeues
interrupted `generating` jobs (safe: step 1); a cross-process **target lock** prevents
two jobs synthesizing the same audio target; book jobs record
`{done,total,current_chapter}` progress and a `stopped_reason` when the sidecar vanishes
or spend runs out.

## Cache invalidation

`chapter_audio.content_version` pins audio to the exact text version. Any base-content
change (owner edit, accepted contribution, re-translation) bumps the version — old audio
rows simply stop matching and the next request regenerates. Overlay saves invalidate
only that user's row.

## Coverage & surfaces

`GET /api/tts/voices` (sidecar catalog; empty when offline — UI degrades),
`GET /api/novels/{id}/audio/chapters?voice_id=…` (chapters with shared audio — drives
"continue listening" and per-chapter play buttons), `GET …/audio/coverage` (all voices —
health panel), `GET /api/tts/jobs/{id}` / `cancel`. Activity feed folds TTS jobs in.

## Operating

```bash
docker compose up -d tts     # GPU host; first start downloads OmniVoice into the HF cache volume
```

On a single small GPU, don't run heavy OCR and TTS simultaneously (compose file note).
Add a narrator: drop a clip in `sidecar-tts/voices/`, restart the sidecar (volume-mounted
read-only — no rebuild). If the sidecar is down, jobs fail with "sidecar unavailable"
and the rest of the app is unaffected. Auth eval: `eval/sidecar_auth_tests.py`.
