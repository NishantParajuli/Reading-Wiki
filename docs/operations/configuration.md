# Configuration reference

> **Source of truth:** `novelwiki/platform/config/settings.py` (compat alias:
> `novelwiki/config/settings.py`). Settings load from environment variables and `.env`
> (pydantic-settings, unknown keys ignored). This page lists **every** setting with its
> default and what it actually controls. A runtime `@model_validator` checks logging
> values and range-checks the AGY block at boot — invalid config refuses to start.

Operating-system environment variables override `.env`, and code defaults apply when
neither supplies a value. `.env.example` is an opinionated deployment template, not a
copy of code defaults (for example it may deliberately override a model or verification
toggle). Unknown/stale template keys are ignored because `extra="ignore"`; confirm the
field exists on `Settings` before relying on it.

At this revision, `.env.example` contains one such ignored legacy key:
`SCRAPER_CONCURRENCY`. Scraping is sequential and controlled by delay/timeout settings;
setting that name has no runtime effect.

## Logging and observability

Application, HTTP, worker, job, and AGY lifecycle logs use a shared structured schema.
See [logging.md](logging.md) for fields, event names, Grafana/Loki queries, and the
sensitive-data boundary.

| Setting | Default | Notes |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG` also emits successful worker/lease heartbeats and maintenance sweeps |
| `LOG_FORMAT` | `json` | one JSON object per line; use `console` for interactive local output |
| `LOG_SERVICE` | `tideglass` | stable service field on every application record |
| `LOG_ENVIRONMENT` | `development` | deployment field; set `production`/`staging` as appropriate |
| `LOG_HTTP_REQUESTS` | `true` | request completion/failure events with request ID, route, status, and duration |
| `LOG_JOB_PROGRESS` | `true` | structured durable-job stage/progress events |

## Database

| Setting | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/novelwiki` | plain `postgresql://` scheme (asyncpg direct — **not** `postgresql+asyncpg://`) |
| `DB_SUPERUSER_URL` | `postgresql://postgres:postgres@localhost:5432/postgres` | used once at startup to auto-create the app DB if missing |

## LLM provider routing (OpenRouter)

| Setting | Default | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | `""` | one key for chat, translation, embeddings, rerank |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | |
| `OPENROUTER_REFERER` / `OPENROUTER_TITLE` | repo URL / app title | attribution headers |
| `MODEL_FLASH` | `deepseek/deepseek-v4-flash` | cheap reader/distiller ("Flash reads…") |
| `MODEL_PRO` | `deepseek/deepseek-v4-pro` | planner/reasoner ("…Pro thinks"); may equal FLASH |
| `MODEL_TRANSLATE` | `deepseek/deepseek-v4-pro` | raw-chapter translation |
| `SEGMENT_MODEL` | `deepseek/deepseek-v4-pro` | import segmentation refinement |
| `EMBED_MODEL` | `cohere/embed-english-v3.0` | |
| `EMBED_DIM` | `1024` | must match the model; sets the pgvector column dimension (HNSW indexes only when ≤ 2000) |
| `EMBED_REQUEST_DIMENSIONS` | `false` | `true` only for models accepting a requested output size (OpenAI `text-embedding-3-*`); fixed-dimension models (Cohere v3) reject the parameter |
| `RERANK_MODEL` | `cohere/rerank-4-fast` | |

## Display

`NOVEL_TITLE` (`The Codex`), `NOVEL_BLURB` — hero/home display strings only; never gate
content.

## Retrieval & agent

| Setting | Default | Notes |
|---|---|---|
| `CHUNK_TARGET_TOKENS` / `CHUNK_OVERLAP` | 500 / 80 | chunking geometry |
| `RRF_K` | 60 | reciprocal-rank-fusion constant |
| `RETRIEVE_K` | 50 | candidates per retriever before fusion |
| `RERANK_TOP_N` | 8 | passages surviving rerank |
| `MAX_ITERATIONS` | 5 | agent plan→act→reason loop cap |
| `BM25_INDEX_PATH` | `./data/bm25_index` | per-novel lexical indexes |
| `BM25_THREAD_OFFLOAD` | `true` | run blocking BM25 ops off the event loop (keep on in prod) |

## Read-side AI cost controls (denial-of-wallet)

| Setting | Default | Notes |
|---|---|---|
| `ASK_MAX_QUERY_CHARS` | 1000 | longer questions → 422 before any provider call |
| `ASK_MAX_UNIQUE_PER_USER_HOUR` | 30 | fixed-window cap on **uncached** AI reads (cache hits free) |
| `ASK_MAX_CONCURRENT_PER_USER` / `ASK_CONCURRENCY_TTL_SECONDS` | 2 / 180 | in-flight slots (self-expiring `ai_request_locks`) |
| `ASK_REQUIRE_VERIFIED` / `ENTITY_PROFILE_SYNTH_REQUIRE_VERIFIED` | `true` | verified email to trigger uncached AI reads |
| `ASK_TOOL_MAX_K` / `ASK_TOOL_MAX_TOP_N` / `ASK_TOOL_MAX_RERANK_HITS` / `ASK_TOOL_MAX_QUERY_CHARS` / `ASK_MAX_TOOL_CALLS_PER_ITER` | 100 / 20 / 100 / 2000 / 4 | hard clamps on *model-planned* tool calls, so the LLM can't be steered into huge fan-outs |

## Extraction accuracy

| Setting | Default | Notes |
|---|---|---|
| `SUMMARY_INPUT_MAX_CHARS` | 48000 | chars of the chapter feeding the running summary rebuild |
| `FUZZY_MATCH_THRESHOLD` / `FUZZY_AUTO_ACCEPT` | 0.35 / 0.6 | pg_trgm entity-linking bands (between them → LLM disambiguation) |
| `SEMANTIC_MATCH_THRESHOLD` | 0.85 | cosine floor for the vector fallback fold-in |
| `EXTRACTION_VERIFY` | `true` | second LLM pass per chapter (catches missed facts/identity reveals; +1 call/chapter) |

## Translation

`TRANSLATE_PREFETCH` (3 — chapters translated in the background after one is opened),
`TRANSLATE_MAX_INPUT_CHARS` (48000).

## Scraper

| Setting | Default | Notes |
|---|---|---|
| `SCRAPER_ADAPTER` / `SCRAPER_BASE_URL` | `fenrirealm` / its URL | legacy defaults for single-source flows |
| `SCRAPER_DELAY` | 1.0 s | politeness delay between fetches |
| `SCRAPER_TIMEOUT_SECONDS` / `SCRAPER_MAX_RESPONSE_MB` | 30 / 8 | network guardrails |
| `SCRAPER_REQUIRE_SAME_HOST` | `true` | binds crawls (incl. redirects/CDN hops) to the source host; adapters declare known extra hosts via `allowed_hosts` |
| `SCRAPER_ALLOWED_HOST_OVERRIDES` | `""` | comma-separated deployment-level extra hosts (prefer adapter-local lists) |

## File import

| Setting | Default | Notes |
|---|---|---|
| `IMPORT_DIR` / `IMPORT_INCOMING_DIR` / `ASSET_DIR` | `./data/imports` / `…/incoming` / `./data/assets` | roots (see [../data/filesystem-layout.md](../data/filesystem-layout.md)) |
| `MAX_UPLOAD_MB` | 50 | single-shot upload cap |
| `MAX_CHUNKED_UPLOAD_MB` / `UPLOAD_CHUNK_MAX_MB` / `UPLOAD_CHUNKED_THRESHOLD_MB` | 1024 / 16 / 40 | resumable-upload total/chunk caps and the client switchover size |
| `IMPORT_UPLOAD_SESSION_TTL_HOURS` | 24 | abandoned `receiving` sessions GC |
| `IMPORT_WORKER_HEARTBEAT_SECONDS` / `IMPORT_LEASE_TIMEOUT_SECONDS` | 30 / 120 | claim-lease renewal / orphan reclaim (timeout must comfortably exceed heartbeat) |
| `IMPORT_AUTO_BUILD_CODEX` | `false` | auto-build codex over the imported range on commit |

## Generic durable jobs

`JOB_WORKER_HEARTBEAT_SECONDS` (30), `JOB_LEASE_TIMEOUT_SECONDS` (180),
`JOB_MAX_ATTEMPTS` (3).

## OCR (scanned PDFs)

| Setting | Default | Notes |
|---|---|---|
| `OCR_SIDECAR_URL` / `OCR_ENABLED` | `http://localhost:8077` / `true` | PaddleOCR PP-StructureV3 sidecar (compose overrides URL to `http://ocr:8077`) |
| `OCR_CONFIDENCE_ESCALATE` | 0.80 | page mean confidence below this → Gemini vision |
| `GEMINI_API_KEY` / `GEMINI_BASE_URL` / `GEMINI_VISION_MODEL` | "" / OpenAI-compatible endpoint / `gemini-2.5-flash` | escalation provider |
| `GEMINI_DAILY_BUDGET` / `GEMINI_RPM` / `GEMINI_PAGES_PER_REQUEST` | 2000 / 10 / 3 | free-tier guards (budget persisted in `provider_budget`) |

## Audiobook TTS

| Setting | Default | Notes |
|---|---|---|
| `TTS_SIDECAR_URL` / `TTS_ENABLED` | `http://localhost:8078` / `true` | OmniVoice sidecar (compose: `http://tts:8078`) |
| `AUDIO_DIR` | `./data/audio` | outside ASSET_DIR on purpose (access-controlled only) |
| `TTS_NUM_STEP` | 32 | diffusion steps (16 = faster/rougher) |
| `TTS_SPEED` / `TTS_PARA_SILENCE_MS` | 1.0 / 350 | pacing |
| `TTS_DEFAULT_VOICE` | `narrator` | |
| `TTS_MAX_BATCH_CHAPTERS` | 100 | hard cap per whole-book job |
| `TTS_OPUS_BITRATE` | `48k` | stored-audio bitrate (ffmpeg libopus) |
| `TTS_TITLE_INTRO` | `true` | spoken "Chapter N. Title." intro |

## Sidecar service auth

| Setting | Notes |
|---|---|
| `SIDECAR_AUTH_TOKEN` | shared token sent as `X-Tideglass-Sidecar-Token`; each sidecar **requires** it (set a long random value in prod) |
| `OCR_SIDECAR_TOKEN` / `TTS_SIDECAR_TOKEN` | per-service overrides (effective values via the `ocr_sidecar_token`/`tts_sidecar_token` properties) |
| *(sidecar env)* `SIDECAR_ALLOW_UNAUTHENTICATED=1` | explicit dev-only opt-out; otherwise expensive endpoints fail closed with no token |

## Sessions, CSRF & web

| Setting | Default | Notes |
|---|---|---|
| `SESSION_SECRET` | `dev-insecure-change-me` | signs/peppers tokens — long random value in prod; rotation invalidates all sessions |
| `SESSION_COOKIE` / `CSRF_COOKIE` | `tg_session` / `tg_csrf` | |
| `SESSION_TTL_DAYS` | 30 | |
| `ALLOWED_ORIGINS` | `http://localhost:8001,http://localhost:8000` | explicit CORS list (credentialed requests forbid `*`) |
| `COOKIE_SECURE` | `true` | set `false` only for plain-HTTP localhost dev |
| `PUBLIC_BASE_URL` | `http://localhost:8001` | builds email links + OAuth redirect URIs |

## Auth abuse throttles (durable fixed windows)

| Flow | Settings (limit / window s) |
|---|---|
| Login | `AUTH_LOGIN_IP_LIMIT` 10, `AUTH_LOGIN_ACCOUNT_LIMIT` 5 / `AUTH_LOGIN_WINDOW_SECONDS` 600 |
| Register | `AUTH_REGISTER_IP_LIMIT` 5 / `AUTH_REGISTER_WINDOW_SECONDS` 3600 |
| Reset request | `AUTH_RESET_REQUEST_IP_LIMIT` 5, `AUTH_RESET_REQUEST_EMAIL_LIMIT` 3 / `AUTH_RESET_REQUEST_WINDOW_SECONDS` 3600 |
| Reset submit | `AUTH_RESET_SUBMIT_IP_LIMIT` 10, `AUTH_RESET_SUBMIT_TOKEN_LIMIT` 5 / `AUTH_RESET_SUBMIT_WINDOW_SECONDS` 3600 |

## Bootstrap admin & migration

`ADMIN_EMAIL` / `ADMIN_PASSWORD` (blank ⇒ skip bootstrap) / `ADMIN_USERNAME` — first
admin created by the guarded multi-user migration, which also adopts any pre-multi-user
library as the admin's Global shelf. `MULTIUSER_MIGRATION_BACKUP_CONFIRMED` (`false`) —
the data-rewriting migration refuses to run on legacy data without an explicit backup
confirmation.

## Email (transactional)

`SMTP_HOST` (blank ⇒ log links instead of sending — dev mode), `SMTP_PORT` 587,
`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` `true`.

## OAuth

`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, `DISCORD_CLIENT_ID`/`DISCORD_CLIENT_SECRET` —
blank hides the button. Redirect URI:
`{PUBLIC_BASE_URL}/api/auth/oauth/{provider}/callback`.

## Monthly quotas (per user; per-user overrides on the user row)

`DEFAULT_QUOTA_TRANSLATED_CHAPTERS` 1000 · `DEFAULT_QUOTA_OCR_PAGES` 3000 ·
`DEFAULT_QUOTA_CODEX_BUILDS` 20 · `DEFAULT_QUOTA_TTS_CHAPTERS` 200 (charged only on
actual generation).

## AGY (Antigravity CLI backend)

Dormant unless `AGY_ENABLED=true` **and** a per-user admin grant exists. Validated at
boot. See [../modules/ai-execution.md](../modules/ai-execution.md) and
[../agy-operator-runbook.md](../agy-operator-runbook.md).

| Setting | Default | Notes |
|---|---|---|
| `AGY_ENABLED` | `false` | global kill switch |
| `AGY_BINARY` / `AGY_MIN_VERSION` / `AGY_BINARY_SHA256` | local path / `1.1.1` / pinned hash | integrity pin; updating AGY is an explicit operator action (empty hash = deliberate unpinned dev) |
| `AGY_WORK_DIR` | `~/.local/share/novelwiki/agy-jobs` | story-bearing workspaces outside checkout + public roots |
| `AGY_MODEL_TRANSLATE` / `AGY_MODEL_CODEX` / `AGY_MODEL_SEGMENT` / `AGY_MODEL_OCR` | Gemini 3.5 Flash (Medium/High/Medium/High) | **exact display names** from `agy models`; preflight hard-fails on catalog drift |
| `AGY_MODE` | `""` | `""` \| `accept-edits` \| `plan` |
| `AGY_MAX_CONCURRENT` | 1 | 1–4 |
| `AGY_PRINT_TIMEOUT_SECONDS` / `AGY_OUTER_TIMEOUT_GRACE_SECONDS` / `AGY_KILL_GRACE_SECONDS` | 1200 / 30 / 10 | subprocess timeout → grace → kill escalation |
| `AGY_STDOUT_MAX_BYTES` / `AGY_STDERR_MAX_BYTES` / `AGY_WORKSPACE_MAX_BYTES` | 1 MiB / 1 MiB / 128 MiB | retention caps |
| `AGY_TRANSLATE_BATCH_CHAPTERS` / `AGY_TRANSLATE_BATCH_MAX_CHARS` | 3 / 120000 | per-invocation batch size |
| `AGY_CODEX_BATCH_CHAPTERS` / `AGY_SEPARATE_CODEX_VERIFY` | 1 / `false` | |
| `AGY_MAX_ATTEMPTS` / `AGY_PROVIDER_RETRY_MINUTES` | 2 / 30 | retry + `waiting_provider` park duration |
| `AGY_SUCCESS_RETENTION_HOURS` / `AGY_FAILURE_RETENTION_HOURS` | 24 / 168 | workspace sweep |
| `AGY_FALLBACK_TO_API_DEFAULT` | `false` | default fallback stance |
| `AGY_PLUGIN_VERSION` / `AGY_PLUGIN_SHA256` | pinned | plugin integrity |
| `AGY_WORKER_HEALTH_TTL_SECONDS` | 90 | heartbeat staleness for `/auth/me` + admin panel |

## Minimal production checklist

`DATABASE_URL`, `DB_SUPERUSER_URL`, `OPENROUTER_API_KEY`, a long random
`SESSION_SECRET`, a long random `SIDECAR_AUTH_TOKEN` (if any sidecar runs),
`ALLOWED_ORIGINS`/`PUBLIC_BASE_URL` for your domain, `COOKIE_SECURE=true`,
`LOG_ENVIRONMENT=production`, `ADMIN_EMAIL`/`ADMIN_PASSWORD` for first boot, SMTP if you
want real email, and — only if scanned-PDF OCR is needed — `GEMINI_API_KEY`.
