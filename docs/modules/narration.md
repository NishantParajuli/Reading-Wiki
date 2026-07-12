# Narration module (`novelwiki/modules/narration/`)

**Responsibility:** audiobook narration: durable TTS jobs (one chapter, or a bounded
whole-book batch), the OmniVoice GPU-sidecar client, the cached-Opus chapter-audio
manifest, and access-controlled audio streaming to the reader's transport UI.
Pipeline walkthrough: [../pipelines/narration.md](../pipelines/narration.md).

**Owned tables:** `tts_jobs`, `chapter_audio`.
**Owned filesystem root:** `AUDIO_DIR` (`./data/audio/` — deliberately **outside**
`ASSET_DIR`, so audio is only reachable through the access-controlled route, never a
public static mount).

---

## Public contract (`public.py`)

Small by design: `NarrationApi` (`schedule_chapter`, `cancel`) and
`NarrationCoverageApi` (`coverage(novel_id)` — used by Experience's health/home
projections). Everything else is internal.

## Application layer

- **`service.py::NarrationService`** — the HTTP-facing use cases, constructed with seven
  ports plus config (`default_voice`, `enabled`, `max_batch_chapters`):
  - `generate_chapter` — Catalog readable-check → overlay-aware cache lookup (exact
    `(novel, chapter, voice, content_version, user-or-base)` match returns immediately,
    **no charge**) → quota `check_available` (`tts_chapters`) → dedupe onto an active
    identical job → create a `scope='chapter'` job.
  - `generate_book` — bounded batch: candidate prose chapters (skipping ones already
    narrated in that voice), capped at `TTS_MAX_BATCH_CHAPTERS` (100), one active book
    job per (novel, voice) via `find_active_book_job`, explicit chapter list stored in
    `options.chapters`.
  - `voices`, `book_status`, `audio_chapters`, `coverage`, `job`/`cancel_job`
    (ownership-scoped), `chapter_status`, `chapter_audio` (path + `AudioFileGone` when
    the row exists but the file vanished).
- **`worker.py::NarrationWorkerService`** — the durable-job orchestration for one claimed
  job, with all effects behind `NarrationWorkerOperations` (load user, spend check,
  cancel check, sidecar availability, per-chapter generation, progress updates).
- **`worker_state.py::NarrationWorkerState`** — persistence policy over the worker
  repository + identity lookup.
- **`dto.py`** (`ChapterAudioCommand`, `BookAudioCommand`, `AudioFile`), **`errors.py`**
  (`AudioFileGone`).
- **`domain/textprep.py`** — chapter text → narratable paragraphs (markup stripping,
  paragraph splitting, number/abbreviation handling), plus the optional spoken intro
  ("Chapter N. Title.", `TTS_TITLE_INTRO`).

## The worker (`adapters/inbound/worker.py`)

A DB-polled loop started by the lifecycle (idempotent `start_worker`/`stop_worker`,
configured with an injected runtime of quota/chapter-text/sidecar/state capabilities):

- **Claim** — atomically flips the oldest `queued` job to `generating`.
- **Restart recovery** — `_requeue_interrupted`: `generating → queued` on boot (safe
  because chapter generation is idempotent against the audio cache; unlike the
  import/generic workers this worker is single-instance-per-DB by design).
- **Per-chapter flow** (`_generate_chapter`): skip if cached → resolve the *requester's*
  text via Reading (overlay-aware: a reader with an edited translation hears their own
  text; that audio row is stamped `user_id`, base audio has `user_id IS NULL`) →
  textprep → sidecar `narrate` (per-paragraph synthesis with the cached voice-clone
  prompt, `TTS_PARA_SILENCE_MS` gaps, `TTS_NUM_STEP` diffusion steps, `TTS_SPEED`) →
  ffmpeg Opus (`TTS_OPUS_BITRATE` 48k) → write under `AUDIO_DIR` → upsert
  `chapter_audio` (partial-unique indexes: one base row and one per-user row per
  `(novel, chapter, voice, version)`) → **meter 1 `tts_chapters` unit only on actual
  generation** (cache hits and skips are never charged).
- **Cross-process target lock** — `_target_lock(key)` prevents two jobs generating the
  same audio target concurrently.
- **Book jobs** — iterate `options.chapters` with cancel checks between chapters,
  progress `{done,total,current_chapter}`, `stopped_reason` recorded when the sidecar
  disappears or spend is exhausted; a cancel keeps completed chapters.
- **States:** `queued → generating → done | failed | canceled`.

## Sidecar client (`adapters/outbound/sidecar.py`)

HTTP client for the OmniVoice GPU service (`TTS_SIDECAR_URL`, default `:8078`):
`sidecar_available()`, `list_voices()` (id/name/language/gender/accent/ready — empty
when offline, so the UI degrades gracefully), `synthesize(text, voice…)` → 24 kHz mono
WAV, `narrate(paragraphs, …)` → whole-chapter audio with consistent cloned voice.
Every call carries the shared service token (`tts_sidecar_token` →
`X-Tideglass-Sidecar-Token`); the sidecar fails closed without it. Voices are cloned from
fixed reference clips in `sidecar-tts/voices/` (see its README; consented/public-domain
audio only).

## HTTP surface (auth required, `/api`)

`GET /tts/voices` · `POST /novels/{id}/chapter/{n}/audio` (returns cached immediately or
schedules) · `GET …/audio/status` · `GET …/audio.opus` (access-controlled FileResponse;
HTTP Range supported for scrubbing) · `POST /novels/{id}/audiobook` ·
`GET /novels/{id}/audiobook/status` · `GET /novels/{id}/audio/chapters` ·
`GET /novels/{id}/audio/coverage` · `GET /tts/jobs/{id}` · `POST /tts/jobs/{id}/cancel`.

## Collaboration notes

- Chapter text comes only through `ChapterTextPort` → Reading's
  `resolve_narration_text` (overlay-aware); access checks through Catalog; quota through
  Identity (`IdentityNarrationQuota` bridge).
- `chapter_audio.content_version` ties audio to the exact text version — base edits or
  accepted contributions invalidate audio naturally (next request regenerates).
- Experience folds TTS jobs into `/api/activity` and uses coverage for
  home ("continue listening") and the novel health panel.
