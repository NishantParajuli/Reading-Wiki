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
| `HOST_WORKER_DATABASE_HOST` | `""` | service-scoped hostname override; host systemd units set `127.0.0.1` so they can share Docker's `host.docker.internal` URLs without copying credentials |

## LLM provider routing (DeepSeek, OpenRouter, Gemini)

When `DEEPSEEK_API_KEY` is non-empty, the configured V4 ids
(`deepseek/deepseek-v4-flash` or `deepseek-v4-flash`, and the equivalent Pro id) are
sent directly to DeepSeek as `deepseek-v4-flash` / `deepseek-v4-pro`. With no native
key, those calls use OpenRouter as before. A configured non-DeepSeek model always uses
OpenRouter. Embeddings and reranking always use OpenRouter regardless of the DeepSeek
key, so `OPENROUTER_API_KEY` remains required.

| Setting | Default | Notes |
|---|---|---|
| `DEEPSEEK_API_KEY` | `""` | enables native DeepSeek V4 text generation when non-empty |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible native endpoint |
| `OPENROUTER_API_KEY` | `""` | embeddings and rerank; chat/translation when native DeepSeek is not selected |
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
| `RRF_K` / `RRF_SOURCE_QUOTA_RATIO` | 60 / 0.4 | reciprocal-rank-fusion constant and the candidate share reserved for each sparse/dense source before reranking |
| `RETRIEVE_K` | 50 | candidates per retriever before fusion |
| `RERANK_TOP_N` | 8 | passages surviving rerank |
| `MAX_ITERATIONS` | 5 | agent plan→act→reason loop cap |
| `BM25_INDEX_PATH` | `./data/bm25_index` | per-novel lexical indexes |
| `BM25_THREAD_OFFLOAD` / `BM25_PREFIX_CACHE_SIZE` | `true` / 4 | run blocking BM25 ops off the event loop and retain a bounded LRU of exact reader-ceiling IDF indexes |

## Read-side AI cost controls (denial-of-wallet)

| Setting | Default | Notes |
|---|---|---|
| `ASK_MAX_QUERY_CHARS` | 1000 | longer questions → 422 before any provider call |
| `ASK_MAX_UNIQUE_PER_USER_HOUR` | 30 | fixed-window cap on **uncached** AI reads (cache hits free) |
| `ASK_MAX_CONCURRENT_PER_USER` / `ASK_CONCURRENCY_TTL_SECONDS` | 2 / 180 | in-flight slots (self-expiring `ai_request_locks`) |
| `ASK_REQUIRE_VERIFIED` / `ENTITY_PROFILE_SYNTH_REQUIRE_VERIFIED` | `true` | verified email to trigger uncached AI reads |
| `CODEX_QA_CACHE_VERSION` / `CODEX_PROFILE_CACHE_VERSION` | `3` / `2` | operator-bumped read-side grounding namespaces; Ask also varies by both model ids, while profile hits require the stored `MODEL_PRO` |
| `ASK_TOOL_MAX_K` / `ASK_TOOL_MAX_QUERY_CHARS` / `ASK_MAX_TOOL_CALLS_PER_ITER` | 100 / 2000 / 4 | hard clamps on *model-planned* tool calls; reranking is host-controlled and accepts only retrieved candidates |

## Extraction accuracy

| Setting | Default | Notes |
|---|---|---|
| `FUZZY_MATCH_THRESHOLD` / `FUZZY_AUTO_ACCEPT` | 0.35 / 0.6 | pg_trgm entity-linking bands (between them → LLM disambiguation) |
| `SEMANTIC_MATCH_THRESHOLD` | 0.85 | cosine floor for the vector fallback fold-in |
| `EXTRACTION_VERIFY` | `true` | direct API only: best-effort second extraction call per chapter; AGY review is controlled separately |

## Bounded Codex memory v2.1

| Setting | Default | Notes |
|---|---|---|
| `CODEX_PIPELINE_VERSION` | `2.1` | generated-row/context version; older generated rows do not satisfy a v2.1 build |
| `CODEX_CONTEXT_MAX_TOKENS` / `CODEX_VERIFY_CONTEXT_MAX_TOKENS` | 48000 / 64000 | primary extraction cap and second-pass cap; verification keeps the same full bounded source/memory plus compact complete draft JSON, so its cap must be at least the primary cap and may not exceed 128000 |
| `CODEX_CONTEXT_MAX_ENTITIES` / `CODEX_CONTEXT_MAX_BACKGROUND_ENTITIES` | 120 / 20 | hard entity caps; all literal current-chapter names are retained or the build fails, while semantic/recent/graph-only background is separately bounded |
| `CODEX_CONTEXT_VECTOR_MIN_SIMILARITY` | 0.45 | floor below which name/chapter vector candidates are ignored |
| `CODEX_CONTEXT_ENTITY_TOKENS` / `CODEX_CONTEXT_STATE_TOKENS` / `CODEX_CONTEXT_THREAD_TOKENS` | 8000 / 2000 / 1000 | independent section budgets |
| `CODEX_RECENT_SUMMARY_CHAPTERS` / `CODEX_CHECKPOINT_CHAPTERS` | 3 / 25 | local continuity and grounded reducer width |
| `CODEX_CHAPTER_SUMMARY_MIN_TOKENS` / `CODEX_CHAPTER_SUMMARY_MAX_TOKENS` | 64 / 300 | source-length-aware validation floor (reduced for short sources) and hard upper bound; the prompt targets 80-220 tokens while the lower floor tolerates normal model variance without encouraging RAG inflation, and internal chunk/ref notation is rejected |
| `CODEX_CHECKPOINT_SUMMARY_MIN_TOKENS` / `CODEX_CHECKPOINT_SUMMARY_MAX_TOKENS` / `CODEX_VOLUME_SUMMARY_MIN_TOKENS` / `CODEX_VOLUME_SUMMARY_MAX_TOKENS` | 200 / 1500 / 300 / 2000 | distributed reducer bounds, dynamically reduced only for short child ranges |
| `CODEX_RECENT_ACTIVITY_CHAPTERS` / `CODEX_CONTEXT_MAX_THREADS` / `CODEX_THREAD_DORMANT_CHAPTERS` | 15 / 10 / 50 | relevance and projected thread-dormancy windows |
| `CODEX_STATE_CONDITION_MAX_AGE_CHAPTERS` / `CODEX_STATE_CUSTODY_MAX_AGE_CHAPTERS` / `CODEX_STATE_GOAL_MAX_AGE_CHAPTERS` | 30 / 50 / 75 | transient state becomes unknown unless reconfirmed |
| `CODEX_STATE_OCCUPATION_MAX_AGE_CHAPTERS` / `CODEX_STATE_LOCATION_MAX_AGE_CHAPTERS` | 100 / 100 | longer-lived transient-state freshness windows |
| `CODEX_READ_MAX_FACTS` / `CODEX_READ_MAX_RELATIONSHIPS` / `CODEX_READ_MAX_TIMELINE_ITEMS` / `CODEX_READ_MAX_ENTITIES` | 200 / 120 / 250 / 200 | hard structured-tool SQL limits |
| `CODEX_ASK_TOTAL_EVIDENCE_TOKENS` / `CODEX_ASK_MAX_DIGEST_TOKENS` | 30000 / 8000 | whole-request raw and distilled evidence budgets |

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

Dormant unless `AGY_ENABLED=true` **and** a per-user admin grant exists. Codex additionally
requires the independent `AGY_CODEX_ENABLED=true` kill switch; keep it false until the
authenticated real-CLI canary passes against the pinned binary. Validated at boot. See
[../modules/ai-execution.md](../modules/ai-execution.md) and
[../agy-operator-runbook.md](../agy-operator-runbook.md).

| Setting | Default | Notes |
|---|---|---|
| `AGY_ENABLED` | `false` | global kill switch |
| `AGY_CODEX_ENABLED` | `false` | independent Codex kill switch, checked both when scheduling and immediately before execution; translation is unaffected |
| `AGY_BINARY` / `AGY_MIN_VERSION` / `AGY_BINARY_SHA256` | local path / `1.1.2` / pinned hash | integrity pin; updating AGY is an explicit operator action (empty hash = deliberate unpinned dev) |
| `AGY_WORK_DIR` | `~/.local/share/novelwiki/agy-jobs` | story-bearing workspaces outside checkout + public roots |
| `AGY_CREDENTIAL_DIR` | `~/.gemini/antigravity-cli` | official CLI-owned login source; NovelWiki verifies ownership/mode and links files into isolated per-run state without reading token contents |
| `AGY_MODEL_TRANSLATE` / `AGY_MODEL_CODEX` / `AGY_MODEL_SEGMENT` / `AGY_MODEL_OCR` | Gemini 3.6 Flash (Medium/High/Medium/High) | **exact display names** from `agy models`; preflight hard-fails on catalog drift |
| `AGY_MODE` | `accept-edits` | `""` \| `accept-edits` \| `plan`; print mode cannot service interactive edit review |
| `AGY_TOOL_PERMISSION` / `AGY_ARTIFACT_REVIEW_POLICY` | `strict` / `always-proceed` | copied into each isolated run state; hooks plus `--sandbox` remain the enforcement boundary |
| `AGY_MAX_CONCURRENT` | 1 | 1–4 |
| `AGY_PRINT_TIMEOUT_SECONDS` / `AGY_OUTER_TIMEOUT_GRACE_SECONDS` / `AGY_KILL_GRACE_SECONDS` | 1200 / 30 / 10 | subprocess timeout → grace → kill escalation |
| `AGY_STDOUT_MAX_BYTES` / `AGY_STDERR_MAX_BYTES` / `AGY_WORKSPACE_MAX_BYTES` | 1 MiB / 1 MiB / 128 MiB | retention caps |
| `AGY_MAX_MODEL_REQUESTS_PER_RUN` / `AGY_MAX_EMPTY_PLANNER_RESPONSES` | 16 / 10 | terminate runaway request/tool loops or planner warnings that continue without output progress |
| `AGY_REQUIRED_LOADED_HOOKS` | 2 | fail closed unless exactly the tool gate and stop validator are reported active from the single pinned hook file |
| `AGY_TRANSLATE_BATCH_CHAPTERS` / `AGY_TRANSLATE_BATCH_MAX_CHARS` | 3 / 120000 | per-invocation batch size |
| `AGY_CODEX_BATCH_CHAPTERS` / `AGY_SEPARATE_CODEX_VERIFY` | 1 / `false` | one chapter per primary AGY run; the primary run must self-review, while `true` adds a separate verification child run |
| `AGY_MAX_ATTEMPTS` / `AGY_PROVIDER_RETRY_MINUTES` | 2 / 30 | retry + `waiting_provider` park duration |
| `AGY_SUCCESS_RETENTION_HOURS` / `AGY_FAILURE_RETENTION_HOURS` | 24 / 168 | workspace sweep |
| `AGY_FALLBACK_TO_API_DEFAULT` | `false` | default fallback stance |
| `AGY_PLUGIN_VERSION` / `AGY_PLUGIN_SHA256` | pinned | plugin integrity |
| `AGY_WORKER_HEALTH_TTL_SECONDS` | 90 | heartbeat staleness for `/auth/me` + admin panel |

## OpenAI Codex App Server backend

Dormant unless `OPENAI_CODEX_ENABLED=true` and an admin grants a user one or more
`openai_codex_workloads`. Extraction additionally requires
`OPENAI_CODEX_CODEX_ENABLED=true`. Authentication is the official `codex login` ChatGPT session
owned by the dedicated worker user, not an application API key. See the
[operator runbook](../openai-codex-operator-runbook.md).

| Setting | Default | Notes |
|---|---|---|
| `OPENAI_CODEX_ENABLED` / `OPENAI_CODEX_CODEX_ENABLED` | `false` / `false` | provider-wide and extraction-only kill switches |
| `OPENAI_CODEX_BINARY` / `OPENAI_CODEX_MIN_VERSION` / `OPENAI_CODEX_BINARY_SHA256` | `~/.local/bin/codex` / `0.146.0` / empty in code | official executable, minimum protocol version, optional integrity pin; `.env.example` pins the tested launcher, and `~` expands to the worker service user's home |
| `OPENAI_CODEX_WORK_DIR` | `~/.local/share/novelwiki/openai-codex-jobs` | private story-bearing run workspaces outside checkout/public roots; `~` expands to the worker service user's home |
| `OPENAI_CODEX_CREDENTIAL_DIR` | `~/.codex` | official auth source under the worker service user's home; only `auth.json` is linked into per-run state, never parsed by NovelWiki |
| `OPENAI_CODEX_MODEL_TRANSLATE` / `OPENAI_CODEX_MODEL_CODEX` | `gpt-5.6-terra` / `gpt-5.6-luna` | Terra is reserved for translation while Luna is preferred for high-volume extraction, verification, disambiguation, and smoke tests; preflight requires both in App Server `model/list` |
| `OPENAI_CODEX_REASONING_TRANSLATE` / `OPENAI_CODEX_REASONING_CODEX` | `xhigh` / `xhigh` | enforced model policy: Terra and Luna must use `xhigh`; other model families may use low, medium, high, xhigh, or max |
| `OPENAI_CODEX_TURN_TIMEOUT_SECONDS` / `OPENAI_CODEX_KILL_GRACE_SECONDS` | 1200 / 10 | turn deadline and process-group termination grace |
| `OPENAI_CODEX_STDOUT_MAX_BYTES` / `OPENAI_CODEX_STDERR_MAX_BYTES` / `OPENAI_CODEX_WORKSPACE_MAX_BYTES` | 16 MiB / 1 MiB / 128 MiB | JSONL, diagnostic-tail, and workspace caps |
| `OPENAI_CODEX_TRANSLATE_BATCH_CHAPTERS` / `OPENAI_CODEX_TRANSLATE_BATCH_MAX_CHARS` | 3 / 120000 | per-turn translation bound |
| `OPENAI_CODEX_SEPARATE_CODEX_VERIFY` | `true` | quality-first default: run a separate Luna/xhigh structured verification child turn for every extracted chapter |
| `OPENAI_CODEX_MAX_ATTEMPTS` / `OPENAI_CODEX_PROVIDER_RETRY_MINUTES` | 2 / 30 | OpenAI Codex job retries (independent of `AGY_MAX_ATTEMPTS`) and provider-capacity parking |
| `OPENAI_CODEX_SUCCESS_RETENTION_HOURS` / `OPENAI_CODEX_FAILURE_RETENTION_HOURS` | 24 / 168 | private workspace retention |
| `OPENAI_CODEX_CONTRACT_VERSION` | `1.3.10` | host prompt/schema contract recorded on every run and heartbeat; 1.3.10 emits artifact schema 2.2 with separate primary/verification context budgets, compact lossless draft transport, exact lexical evidence locality, verified-only bounded contiguous-anchor canonicalization, safe regular plural and possessive-number matching, semantic verifier repair, bounded evidence/claim-alignment/duplicate-thread recovery, one strongly connected verifier-reviewed thread-topic override, and durable retry progress while retaining pipeline-2.1 database rows and the Luna/xhigh policy |
| `OPENAI_CODEX_WORKER_HEALTH_TTL_SECONDS` | 90 | heartbeat staleness for capabilities/admin health |

## Minimal production checklist

`DATABASE_URL`, `DB_SUPERUSER_URL`, `OPENROUTER_API_KEY`, optionally
`DEEPSEEK_API_KEY` for native V4 generation, a long random
`SESSION_SECRET`, a long random `SIDECAR_AUTH_TOKEN` (if any sidecar runs),
`ALLOWED_ORIGINS`/`PUBLIC_BASE_URL` for your domain, `COOKIE_SECURE=true`,
`LOG_ENVIRONMENT=production`, `ADMIN_EMAIL`/`ADMIN_PASSWORD` for first boot, SMTP if you
want real email, and — only if scanned-PDF OCR is needed — `GEMINI_API_KEY`.
