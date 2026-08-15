from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _replace_database_host(value: str, host: str) -> str:
    """Replace only a DSN hostname while preserving credentials and other URL parts."""
    host = host.strip()
    if not host or any(char in host for char in "/@?#") or any(char.isspace() for char in host):
        raise ValueError("HOST_WORKER_DATABASE_HOST must be a hostname or IP address")
    parsed = urlsplit(value)
    if not parsed.hostname:
        raise ValueError("database URL must contain a hostname")
    credentials = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    rendered_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(parsed._replace(netloc=f"{credentials}{rendered_host}{port}"))

class Settings(BaseSettings):
    # Single-line JSON is the production/default contract for Docker/journald → Loki/Grafana.
    # Console mode is available for interactive local work.  DEBUG additionally exposes lease
    # and worker heartbeats; story text, prompts, credentials, and provider output stay excluded.
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    LOG_SERVICE: str = "tideglass"
    LOG_ENVIRONMENT: str = "development"
    LOG_HTTP_REQUESTS: bool = True
    LOG_JOB_PROGRESS: bool = True

    # NOTE: asyncpg expects a plain `postgresql://` scheme (NOT the SQLAlchemy
    # `postgresql+asyncpg://` dialect form) — both the pool and the schema
    # bootstrap connect via asyncpg directly.
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/novelwiki"
    DB_SUPERUSER_URL: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    # Host-only workers share Docker's .env, where host.docker.internal is correct for
    # containers but may not resolve on Linux itself. The systemd units set this to
    # 127.0.0.1; ordinary web/CLI processes leave it empty.
    HOST_WORKER_DATABASE_HOST: str = ""

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_REFERER: str = "https://github.com/epick/novelwiki"
    OPENROUTER_TITLE: str = "Spoiler-Aware Webnovel Wiki"

    # Native DeepSeek is preferred for the V4 text models whenever this key is set.
    # OpenRouter remains the embedding/rerank provider (and the chat route for
    # non-DeepSeek model ids), so its credential is still required.
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # Presentation metadata for the UI hero/home surface. These are display-only
    # and never gate content — purely the title/blurb the reader sees.
    NOVEL_TITLE: str = "The Codex"
    NOVEL_BLURB: str = "A spoiler-safe wiki for the novel you're reading — every fact bounded to where you are."

    # "Flash reads, Pro thinks" — set these to two distinct models to realize the
    # cost/quality split (e.g. a cheap model for reading/distilling and a stronger
    # one for planning/synthesis). They may legitimately be the same model.
    MODEL_FLASH: str = "deepseek/deepseek-v4-flash"
    MODEL_PRO: str = "deepseek/deepseek-v4-pro"

    # Model used to translate raw (foreign-language) chapters. The default OpenRouter
    # id is normalized to DeepSeek's native id when DEEPSEEK_API_KEY is set. Used by
    # the Phase 2 translation pipeline (on-demand when a raw chapter is opened, +
    # background prefetch).
    MODEL_TRANSLATE: str = "deepseek/deepseek-v4-pro"
    # How many upcoming raw chapters to translate in the background after one is opened.
    TRANSLATE_PREFETCH: int = 3
    # Guard against pathologically long chapters being sent to the translator in one call.
    TRANSLATE_MAX_INPUT_CHARS: int = 48000

    EMBED_MODEL: str = "cohere/embed-english-v3.0"
    EMBED_DIM: int = 1024
    # Set True for models that support a requested output size (e.g. OpenAI
    # text-embedding-3-*), so EMBED_DIM is honored. Leave False for models with a
    # fixed native dimension (e.g. Cohere embed-v3), which reject the parameter.
    EMBED_REQUEST_DIMENSIONS: bool = False

    RERANK_MODEL: str = "cohere/rerank-4-fast"

    CHUNK_TARGET_TOKENS: int = 500
    CHUNK_OVERLAP: int = 80
    RRF_K: int = 60
    # Reserve this share of the pre-rerank candidate set for the top results
    # from each source so RRF consensus cannot suppress dense-only evidence.
    RRF_SOURCE_QUOTA_RATIO: float = 0.4
    RETRIEVE_K: int = 50
    RERANK_TOP_N: int = 8
    MAX_ITERATIONS: int = 5
    BM25_INDEX_PATH: str = "./data/bm25_index"
    # Run BM25's synchronous tokenize/index/search off the event loop (asyncio.to_thread)
    # so a heavy lexical search can't stall unrelated requests. Leave True in prod.
    BM25_THREAD_OFFLOAD: bool = True
    BM25_PREFIX_CACHE_SIZE: int = 4

    # ── Read-side AI cost controls (denial-of-wallet guards for /ask + profile synth) ──
    # Uncached AI reads (agentic Q&A, entity-profile synthesis) fan out to embeddings,
    # rerank, and multiple model calls, so they are gated the same way costly writes are:
    # a verified email, a fixed per-hour cap on how many UNCACHED requests a user may
    # trigger, and a small concurrency ceiling. Cache hits are free and skip every gate.
    ASK_MAX_QUERY_CHARS: int = 1000              # reject longer questions (422) before any provider call
    ASK_MAX_UNIQUE_PER_USER_HOUR: int = 30        # fixed-window cap on uncached AI reads per user per hour
    ASK_MAX_CONCURRENT_PER_USER: int = 2          # max simultaneous in-flight uncached AI reads per user
    ASK_CONCURRENCY_TTL_SECONDS: int = 180        # concurrency-slot lease TTL (auto-reclaimed if a request dies)
    ASK_REQUIRE_VERIFIED: bool = True             # uncached /ask needs a verified email
    ENTITY_PROFILE_SYNTH_REQUIRE_VERIFIED: bool = True  # uncached profile synthesis needs a verified email
    # Bump either namespace whenever its prompts/grounding contract changes. The model
    # ids are also included in Q&A keys and checked on profile-cache reads.
    CODEX_QA_CACHE_VERSION: str = "3"
    CODEX_PROFILE_CACHE_VERSION: str = "2"
    # Hard caps on what a model-planned tool call may request, so the LLM can't be steered
    # into a huge fan-out. Applied in the agent's execute_tool dispatcher.
    ASK_TOOL_MAX_K: int = 100                     # clamp hybrid_search k
    ASK_TOOL_MAX_QUERY_CHARS: int = 2000          # reject longer model-supplied tool queries
    ASK_MAX_TOOL_CALLS_PER_ITER: int = 4          # tool calls processed per planner iteration

    # ── Extraction accuracy knobs ──
    # Entity linking thresholds (pg_trgm similarity, 0..1). A fuzzy candidate must
    # clear FUZZY_MATCH_THRESHOLD to be considered at all; a *single* candidate is
    # auto-accepted only at/above FUZZY_AUTO_ACCEPT — anything in between is sent to
    # the LLM disambiguator so two similarly-named-but-distinct entities don't merge.
    FUZZY_MATCH_THRESHOLD: float = 0.35
    FUZZY_AUTO_ACCEPT: float = 0.6
    # Cosine-similarity floor for the vector fallback to fold a mention into an
    # existing entity (higher = fewer false merges, more duplicates).
    SEMANTIC_MATCH_THRESHOLD: float = 0.85
    # Run a second LLM pass over each chapter to catch facts/relationships/events
    # and (critically) identity reveals the first extraction missed. Costs one
    # extra call per chapter; accuracy-first default is on.
    EXTRACTION_VERIFY: bool = True

    # ── Bounded Codex memory (pipeline v2.1) ──────────────────────────────
    # The provider context window is emergency headroom, not an application
    # budget.  Every extraction is packed under these deterministic limits so
    # chapter 1,400 costs and attends like chapter 40.
    CODEX_PIPELINE_VERSION: str = "2.1"
    CODEX_CONTEXT_MAX_TOKENS: int = 48_000
    CODEX_VERIFY_CONTEXT_MAX_TOKENS: int = 64_000
    CODEX_CONTEXT_MAX_ENTITIES: int = 120
    CODEX_CONTEXT_MAX_BACKGROUND_ENTITIES: int = 20
    CODEX_CONTEXT_VECTOR_MIN_SIMILARITY: float = 0.45
    CODEX_CONTEXT_ENTITY_TOKENS: int = 8_000
    CODEX_CONTEXT_STATE_TOKENS: int = 2_000
    CODEX_CONTEXT_THREAD_TOKENS: int = 1_000
    CODEX_RECENT_SUMMARY_CHAPTERS: int = 3
    CODEX_CHECKPOINT_CHAPTERS: int = 25
    CODEX_CHAPTER_SUMMARY_MIN_TOKENS: int = 64
    CODEX_CHAPTER_SUMMARY_MAX_TOKENS: int = 300
    CODEX_CHECKPOINT_SUMMARY_MIN_TOKENS: int = 200
    CODEX_CHECKPOINT_SUMMARY_MAX_TOKENS: int = 1_500
    CODEX_VOLUME_SUMMARY_MIN_TOKENS: int = 300
    CODEX_VOLUME_SUMMARY_MAX_TOKENS: int = 2_000
    CODEX_RECENT_ACTIVITY_CHAPTERS: int = 15
    CODEX_CONTEXT_MAX_THREADS: int = 10
    CODEX_THREAD_DORMANT_CHAPTERS: int = 50
    CODEX_STATE_CONDITION_MAX_AGE_CHAPTERS: int = 30
    CODEX_STATE_CUSTODY_MAX_AGE_CHAPTERS: int = 50
    CODEX_STATE_GOAL_MAX_AGE_CHAPTERS: int = 75
    CODEX_STATE_OCCUPATION_MAX_AGE_CHAPTERS: int = 100
    CODEX_STATE_LOCATION_MAX_AGE_CHAPTERS: int = 100

    # UI history is paginated independently, while model-facing tools receive
    # much smaller bounded slices.  These caps prevent a long-running
    # protagonist from turning one profile/timeline call into a book-sized
    # prompt.
    CODEX_READ_MAX_FACTS: int = 200
    CODEX_READ_MAX_RELATIONSHIPS: int = 120
    CODEX_READ_MAX_TIMELINE_ITEMS: int = 250
    CODEX_READ_MAX_ENTITIES: int = 200
    CODEX_ASK_TOTAL_EVIDENCE_TOKENS: int = 30_000
    CODEX_ASK_MAX_DIGEST_TOKENS: int = 8_000

    # Scraper: pick a site adapter by key (see scraper/adapters.py registry).
    SCRAPER_ADAPTER: str = "fenrirealm"
    SCRAPER_BASE_URL: str = "https://fenrirealm.com"
    SCRAPER_DELAY: float = 1.0
    SCRAPER_TIMEOUT_SECONDS: float = 30.0
    SCRAPER_MAX_RESPONSE_MB: int = 8
    SCRAPER_REQUIRE_SAME_HOST: bool = True
    # Comma-separated hostnames adapters may fetch in addition to the source host.
    # Prefer adapter-local allowlists for known APIs; use this only for deployment overrides.
    SCRAPER_ALLOWED_HOST_OVERRIDES: str = ""

    # ── File import (EPUB/PDF ingestion) ──
    # Heavy artifacts live on disk; the DB holds pointers + the editable plan.
    IMPORT_DIR: str = "./data/imports"
    IMPORT_INCOMING_DIR: str = "./data/imports/incoming"   # host watched-folder drop (big files)
    ASSET_DIR: str = "./data/assets"
    MAX_UPLOAD_MB: int = 50                                 # single-shot multipart cap
    MAX_CHUNKED_UPLOAD_MB: int = 1024                       # total cap for a resumable (chunked) upload
    UPLOAD_CHUNK_MAX_MB: int = 16                           # max size of one resumable-upload chunk
    UPLOAD_CHUNKED_THRESHOLD_MB: int = 40                   # client switches to chunked upload above this
    IMPORT_UPLOAD_SESSION_TTL_HOURS: int = 24              # abandoned 'receiving' sessions are GC'd after this
    # Multi-worker claim lease: a worker stamps + periodically renews `claimed_at` on the job it
    # holds; a claim whose lease goes unrenewed for the timeout is considered orphaned (its worker
    # crashed/was killed) and is reclaimable. Timeout must comfortably exceed the heartbeat.
    IMPORT_WORKER_HEARTBEAT_SECONDS: int = 30
    IMPORT_LEASE_TIMEOUT_SECONDS: int = 120
    IMPORT_AUTO_BUILD_CODEX: bool = False                   # build codex over the imported range on commit

    # ── Generic durable jobs (scrape/codex/translation) ──
    # Same claim-lease model as the import worker: a worker heartbeats the job it holds; a lease
    # unrenewed past the timeout is reclaimed. A crashed/failed job is retried up to JOB_MAX_ATTEMPTS.
    JOB_WORKER_HEARTBEAT_SECONDS: int = 30
    JOB_LEASE_TIMEOUT_SECONDS: int = 180
    JOB_MAX_ATTEMPTS: int = 3

    # ── Hybrid Antigravity CLI backend ────────────────────────────────────
    # AGY is deliberately dormant unless both this global switch and an admin-owned
    # per-user workload grant are enabled.  The CLI keeps its own official
    # browser/keyring authentication; no AGY credential belongs in NovelWiki's env.
    AGY_ENABLED: bool = False
    # Independent incident kill switch: translation can remain available while
    # Codex extraction is contained or being canaried.
    AGY_CODEX_ENABLED: bool = False
    AGY_BINARY: str = "/home/nishantp/.local/bin/agy"
    AGY_MIN_VERSION: str = "1.1.2"
    # Integrity pin for the locally verified 1.1.2 binary (2026-07-15).  Updating
    # AGY is an explicit operator action: re-run preflight/golden tests, then update
    # this hash.  Set to an empty string only for a deliberate unpinned dev setup.
    AGY_BINARY_SHA256: str = "70bf6eaf2e82fbb243db999b9c7c61fcf7f6e537f41980650eb2341ed84b24de"
    # Keep story-bearing workspaces outside both the checkout and public ASSET_DIR.
    AGY_WORK_DIR: str = str(Path.home() / ".local" / "share" / "novelwiki" / "agy-jobs")
    # The official CLI owns this credential directory. NovelWiki never parses the
    # OAuth token; per-run CLI state links only the credential files needed for the
    # authenticated CLI session and keeps mutable brain/scratch data isolated.
    AGY_CREDENTIAL_DIR: str = str(Path.home() / ".gemini" / "antigravity-cli")

    # Exact display names from `agy models`; preflight hard-fails on catalog drift.
    AGY_MODEL_TRANSLATE: str = "Gemini 3.6 Flash (Medium)"
    AGY_MODEL_CODEX: str = "Gemini 3.6 Flash (High)"
    AGY_MODEL_SEGMENT: str = "Gemini 3.6 Flash (Medium)"
    AGY_MODEL_OCR: str = "Gemini 3.6 Flash (High)"
    # Print mode is non-interactive, so request/review workflows cannot be its
    # control plane. Hooks and the sandbox remain the safety boundary.
    AGY_MODE: str = "accept-edits"
    AGY_TOOL_PERMISSION: str = "strict"
    AGY_ARTIFACT_REVIEW_POLICY: str = "always-proceed"

    AGY_MAX_CONCURRENT: int = 1
    AGY_PRINT_TIMEOUT_SECONDS: int = 1200
    AGY_OUTER_TIMEOUT_GRACE_SECONDS: int = 30
    AGY_KILL_GRACE_SECONDS: int = 10
    AGY_STDOUT_MAX_BYTES: int = 1_048_576
    AGY_STDERR_MAX_BYTES: int = 1_048_576
    AGY_WORKSPACE_MAX_BYTES: int = 134_217_728
    # One AGY tool turn normally produces one streamGenerateContent request. Stop
    # a runaway agent before it can burn an unbounded subscription context.
    AGY_MAX_MODEL_REQUESTS_PER_RUN: int = 16
    # AGY 1.1.2 emits this warning for normal tool steps too. Only treat a run as
    # stalled after this many consecutive warnings without output-tree progress.
    AGY_MAX_EMPTY_PLANNER_RESPONSES: int = 10
    # The bundled plugin currently registers a tool gate and a stop validator.
    AGY_REQUIRED_LOADED_HOOKS: int = 2

    AGY_TRANSLATE_BATCH_CHAPTERS: int = 3
    AGY_TRANSLATE_BATCH_MAX_CHARS: int = 120_000
    AGY_CODEX_BATCH_CHAPTERS: int = 1
    AGY_SEPARATE_CODEX_VERIFY: bool = False

    AGY_MAX_ATTEMPTS: int = 2
    AGY_PROVIDER_RETRY_MINUTES: int = 30
    AGY_SUCCESS_RETENTION_HOURS: int = 24
    AGY_FAILURE_RETENTION_HOURS: int = 168
    AGY_FALLBACK_TO_API_DEFAULT: bool = False
    AGY_PLUGIN_VERSION: str = "1.4.4"
    AGY_PLUGIN_SHA256: str = "e6eb9407806cfbea32966331f2f6d62cc8cdc4d509ec1c150db9ae27d3b5f360"
    # Worker health is considered stale after this interval for /auth/me and admin UI.
    AGY_WORKER_HEALTH_TTL_SECONDS: int = 90

    # ── OpenAI Codex App Server subscription backend ─────────────────
    # This is a separate, opt-in backend that uses the official Codex login owned
    # by the dedicated worker OS account. NovelWiki never reads the OAuth token.
    OPENAI_CODEX_ENABLED: bool = False
    OPENAI_CODEX_CODEX_ENABLED: bool = False
    OPENAI_CODEX_BINARY: str = str(Path.home() / ".local" / "bin" / "codex")
    OPENAI_CODEX_MIN_VERSION: str = "0.146.0"
    OPENAI_CODEX_BINARY_SHA256: str = ""
    OPENAI_CODEX_WORK_DIR: str = str(
        Path.home() / ".local" / "share" / "novelwiki" / "openai-codex-jobs"
    )
    OPENAI_CODEX_CREDENTIAL_DIR: str = str(Path.home() / ".codex")
    # Current model roles: Luna/xhigh for high-volume Codex work, Terra/xhigh
    # for translation.  The validator below keeps the deployment from silently
    # weakening either role through an environment override.
    OPENAI_CODEX_MODEL_TRANSLATE: str = "gpt-5.6-terra"
    OPENAI_CODEX_MODEL_CODEX: str = "gpt-5.6-luna"
    OPENAI_CODEX_REASONING_TRANSLATE: str = "xhigh"
    OPENAI_CODEX_REASONING_CODEX: str = "xhigh"
    OPENAI_CODEX_TURN_TIMEOUT_SECONDS: int = 1200
    OPENAI_CODEX_KILL_GRACE_SECONDS: int = 10
    OPENAI_CODEX_STDOUT_MAX_BYTES: int = 16_777_216
    OPENAI_CODEX_STDERR_MAX_BYTES: int = 1_048_576
    OPENAI_CODEX_WORKSPACE_MAX_BYTES: int = 134_217_728
    OPENAI_CODEX_TRANSLATE_BATCH_CHAPTERS: int = 3
    OPENAI_CODEX_TRANSLATE_BATCH_MAX_CHARS: int = 120_000
    OPENAI_CODEX_SEPARATE_CODEX_VERIFY: bool = True
    OPENAI_CODEX_MAX_ATTEMPTS: int = 2
    OPENAI_CODEX_PROVIDER_RETRY_MINUTES: int = 30
    OPENAI_CODEX_SUCCESS_RETENTION_HOURS: int = 24
    OPENAI_CODEX_FAILURE_RETENTION_HOURS: int = 168
    OPENAI_CODEX_CONTRACT_VERSION: str = "1.3.10"
    OPENAI_CODEX_WORKER_HEALTH_TTL_SECONDS: int = 90

    # Text segmentation/cleanup LLM (native DeepSeek when configured, otherwise OpenRouter).
    SEGMENT_MODEL: str = "deepseek/deepseek-v4-pro"

    # Vision provider — Gemini via its OpenAI-compatible endpoint. Used for scanned-PDF OCR
    # escalation (S3); the daily budget + RPM guards keep us inside the free tier.
    GEMINI_API_KEY: str = ""
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    GEMINI_VISION_MODEL: str = "gemini-2.5-flash"
    GEMINI_DAILY_BUDGET: int = 2000          # margin under the ~2.5k/day free tier
    GEMINI_RPM: int = 10
    GEMINI_PAGES_PER_REQUEST: int = 3

    # OCR sidecar (PaddleOCR PP-StructureV3) on localhost (S3; separate GPU deploy).
    OCR_SIDECAR_URL: str = "http://localhost:8077"
    OCR_ENABLED: bool = True
    OCR_CONFIDENCE_ESCALATE: float = 0.80    # page mean confidence below this → Gemini

    # ── Audiobook TTS (OmniVoice sidecar) ──────────────────────────────────
    # Narration runs on a separate GPU sidecar (localhost:8078) and is generated as durable
    # background jobs, then cached + streamed to the reader. Voice cloning with a fixed clip
    # per narrator keeps one consistent voice across a whole book.
    TTS_SIDECAR_URL: str = "http://localhost:8078"
    TTS_ENABLED: bool = True
    # Generated narration lives here, deliberately OUTSIDE ASSET_DIR (which is mounted public
    # at /assets) so private-novel audio is only reachable via the access-controlled route.
    AUDIO_DIR: str = "./data/audio"
    TTS_NUM_STEP: int = 32                    # OmniVoice diffusion steps (16 = faster/rougher)
    TTS_SPEED: float = 1.0                    # narration speed factor (>1 faster)
    TTS_PARA_SILENCE_MS: int = 350            # silence inserted between paragraphs
    TTS_DEFAULT_VOICE: str = "narrator"
    TTS_MAX_BATCH_CHAPTERS: int = 100         # hard cap of chapters per "narrate book" job
    TTS_OPUS_BITRATE: str = "48k"             # ffmpeg libopus bitrate for stored audio
    TTS_TITLE_INTRO: bool = True              # prepend "Chapter N. <title>." spoken intro

    # ── Sidecar service auth (OCR + TTS) ───────────────────────────────────
    # The OCR/TTS sidecars run the expensive GPU endpoints (/ocr, /synthesize, /narrate). When a
    # token is configured the web app sends it as `X-Tideglass-Sidecar-Token` and each sidecar
    # REQUIRES it — so even if a sidecar port is reachable, only the web app can drive it. Sidecars
    # fail closed when no token is configured unless SIDECAR_ALLOW_UNAUTHENTICATED=1 is explicitly
    # set for local-only development. A per-service token (OCR_/TTS_) overrides the shared one.
    SIDECAR_AUTH_TOKEN: str = ""
    OCR_SIDECAR_TOKEN: str = ""
    TTS_SIDECAR_TOKEN: str = ""

    @property
    def ocr_sidecar_token(self) -> str:
        """Effective token the web app presents to the OCR sidecar ("" = send no header)."""
        return self.OCR_SIDECAR_TOKEN or self.SIDECAR_AUTH_TOKEN

    @property
    def tts_sidecar_token(self) -> str:
        """Effective token the web app presents to the TTS sidecar ("" = send no header)."""
        return self.TTS_SIDECAR_TOKEN or self.SIDECAR_AUTH_TOKEN

    # ── Multi-user / auth ──────────────────────────────────────────────────
    # Server-side opaque sessions backed by a DB table; the browser only holds an
    # httpOnly+Secure cookie. SESSION_SECRET signs/peppers tokens — set a long random
    # value in prod (a changed secret invalidates all sessions).
    SESSION_SECRET: str = "dev-insecure-change-me"
    SESSION_COOKIE: str = "tg_session"
    CSRF_COOKIE: str = "tg_csrf"
    SESSION_TTL_DAYS: int = 30
    AUTH_LOGIN_IP_LIMIT: int = 10
    AUTH_LOGIN_ACCOUNT_LIMIT: int = 5
    AUTH_LOGIN_WINDOW_SECONDS: int = 600
    AUTH_REGISTER_IP_LIMIT: int = 5
    AUTH_REGISTER_WINDOW_SECONDS: int = 3600
    AUTH_RESET_REQUEST_IP_LIMIT: int = 5
    AUTH_RESET_REQUEST_EMAIL_LIMIT: int = 3
    AUTH_RESET_REQUEST_WINDOW_SECONDS: int = 3600
    AUTH_RESET_SUBMIT_IP_LIMIT: int = 10
    AUTH_RESET_SUBMIT_TOKEN_LIMIT: int = 5
    AUTH_RESET_SUBMIT_WINDOW_SECONDS: int = 3600
    # Browsers reject `Access-Control-Allow-Origin: *` together with credentialed
    # requests, so list explicit origins. The SPA is served same-origin in prod; these
    # cover the tunnel domain + local dev. Comma-separated in the env var.
    ALLOWED_ORIGINS: str = "http://localhost:8001,http://localhost:8000"
    # Marked Secure so the cookie only rides HTTPS. Set False for plain-HTTP localhost dev.
    COOKIE_SECURE: bool = True

    # First admin, bootstrapped by the migration / `python -m novelwiki.db.migrate_multiuser`.
    # The existing (pre-multi-user) library is reassigned to this user as the Global shelf.
    ADMIN_EMAIL: str = "admin@example.com"
    ADMIN_PASSWORD: str = ""                  # required to bootstrap; leave blank to skip
    ADMIN_USERNAME: str = "admin"
    # Data-rewriting legacy migration guard. Leave false for normal app starts; set true
    # only after taking/restoring/testing a pg_dump, or use the CLI's explicit prompt.
    MULTIUSER_MIGRATION_BACKUP_CONFIRMED: bool = False

    # Transactional email (verification + password reset). Without an SMTP host the app
    # still runs but logs the verification link instead of sending it (handy in dev).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "Tideglass <no-reply@tideglass.local>"
    SMTP_STARTTLS: bool = True
    # Public base URL used to build links in emails + OAuth redirects (no trailing slash).
    PUBLIC_BASE_URL: str = "http://localhost:8001"

    # OAuth providers (optional; leave blank to hide the button). Redirect URI is
    # {PUBLIC_BASE_URL}/api/auth/oauth/{provider}/callback.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""

    # Monthly per-user spend quotas (admin-adjustable per user; NULL on the user row
    # falls back to these). Generous by default for a normal reader.
    DEFAULT_QUOTA_TRANSLATED_CHAPTERS: int = 1000
    DEFAULT_QUOTA_OCR_PAGES: int = 3000
    DEFAULT_QUOTA_CODEX_BUILDS: int = 20
    DEFAULT_QUOTA_TTS_CHAPTERS: int = 200    # chapters narrated per month (charged only on actual generation)

    @model_validator(mode="after")
    def _validate_runtime_settings(self):
        if self.HOST_WORKER_DATABASE_HOST:
            self.DATABASE_URL = _replace_database_host(
                self.DATABASE_URL, self.HOST_WORKER_DATABASE_HOST
            )
            self.DB_SUPERUSER_URL = _replace_database_host(
                self.DB_SUPERUSER_URL, self.HOST_WORKER_DATABASE_HOST
            )
        if self.LOG_LEVEL.strip().upper() not in {
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
        }:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        if self.LOG_FORMAT not in {"json", "console"}:
            raise ValueError("LOG_FORMAT must be 'json' or 'console'")
        if self.AGY_MODE not in ("", "accept-edits", "plan"):
            raise ValueError("AGY_MODE must be empty, 'accept-edits', or 'plan'")
        if self.AGY_TOOL_PERMISSION not in {
            "request-review", "proceed-in-sandbox", "always-proceed", "strict"
        }:
            raise ValueError("AGY_TOOL_PERMISSION has an unsupported value")
        if self.AGY_ARTIFACT_REVIEW_POLICY not in {
            "asks-for-review", "agent-decides", "always-proceed"
        }:
            raise ValueError("AGY_ARTIFACT_REVIEW_POLICY has an unsupported value")
        if not 1 <= self.AGY_MAX_CONCURRENT <= 4:
            raise ValueError("AGY_MAX_CONCURRENT must be between 1 and 4")
        if not 60 <= self.AGY_PRINT_TIMEOUT_SECONDS <= 7200:
            raise ValueError("AGY_PRINT_TIMEOUT_SECONDS must be between 60 and 7200")
        if not 1 <= self.AGY_KILL_GRACE_SECONDS <= 60:
            raise ValueError("AGY_KILL_GRACE_SECONDS must be between 1 and 60")
        if not 1 <= self.AGY_TRANSLATE_BATCH_CHAPTERS <= 10:
            raise ValueError("AGY_TRANSLATE_BATCH_CHAPTERS must be between 1 and 10")
        if not 1_000 <= self.AGY_TRANSLATE_BATCH_MAX_CHARS <= 500_000:
            raise ValueError("AGY_TRANSLATE_BATCH_MAX_CHARS is outside the safe range")
        if not 1 <= self.AGY_MAX_ATTEMPTS <= 5:
            raise ValueError("AGY_MAX_ATTEMPTS must be between 1 and 5")
        if min(self.AGY_STDOUT_MAX_BYTES, self.AGY_STDERR_MAX_BYTES) < 4096:
            raise ValueError("AGY stream retention limits must be at least 4096 bytes")
        if self.AGY_WORKSPACE_MAX_BYTES < 1_048_576:
            raise ValueError("AGY_WORKSPACE_MAX_BYTES must be at least 1 MiB")
        if not 1 <= self.AGY_MAX_MODEL_REQUESTS_PER_RUN <= 100:
            raise ValueError("AGY_MAX_MODEL_REQUESTS_PER_RUN must be between 1 and 100")
        if not 0 <= self.AGY_MAX_EMPTY_PLANNER_RESPONSES <= 20:
            raise ValueError("AGY_MAX_EMPTY_PLANNER_RESPONSES must be between 0 and 20")
        if not 1 <= self.AGY_REQUIRED_LOADED_HOOKS <= 20:
            raise ValueError("AGY_REQUIRED_LOADED_HOOKS must be between 1 and 20")
        for field in ("AGY_MODEL_TRANSLATE", "AGY_MODEL_CODEX", "AGY_MODEL_SEGMENT", "AGY_MODEL_OCR"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be empty")
        if not 60 <= self.OPENAI_CODEX_TURN_TIMEOUT_SECONDS <= 7200:
            raise ValueError("OPENAI_CODEX_TURN_TIMEOUT_SECONDS must be between 60 and 7200")
        if not 1 <= self.OPENAI_CODEX_KILL_GRACE_SECONDS <= 60:
            raise ValueError("OPENAI_CODEX_KILL_GRACE_SECONDS must be between 1 and 60")
        if not 1 <= self.OPENAI_CODEX_TRANSLATE_BATCH_CHAPTERS <= 10:
            raise ValueError("OPENAI_CODEX_TRANSLATE_BATCH_CHAPTERS must be between 1 and 10")
        if not 1_000 <= self.OPENAI_CODEX_TRANSLATE_BATCH_MAX_CHARS <= 500_000:
            raise ValueError("OPENAI_CODEX_TRANSLATE_BATCH_MAX_CHARS is outside the safe range")
        if not 1 <= self.OPENAI_CODEX_MAX_ATTEMPTS <= 5:
            raise ValueError("OPENAI_CODEX_MAX_ATTEMPTS must be between 1 and 5")
        if min(self.OPENAI_CODEX_STDOUT_MAX_BYTES, self.OPENAI_CODEX_STDERR_MAX_BYTES) < 4096:
            raise ValueError("OpenAI Codex stream retention limits must be at least 4096 bytes")
        if self.OPENAI_CODEX_WORKSPACE_MAX_BYTES < 1_048_576:
            raise ValueError("OPENAI_CODEX_WORKSPACE_MAX_BYTES must be at least 1 MiB")
        if not 1 <= self.CODEX_CONTEXT_MAX_BACKGROUND_ENTITIES <= self.CODEX_CONTEXT_MAX_ENTITIES:
            raise ValueError(
                "CODEX_CONTEXT_MAX_BACKGROUND_ENTITIES must be between 1 and "
                "CODEX_CONTEXT_MAX_ENTITIES"
            )
        if not (
            self.CODEX_CONTEXT_MAX_TOKENS
            <= self.CODEX_VERIFY_CONTEXT_MAX_TOKENS
            <= 128_000
        ):
            raise ValueError(
                "CODEX_VERIFY_CONTEXT_MAX_TOKENS must be between the primary Codex "
                "context cap and 128000"
            )
        if not (
            20 <= self.CODEX_CHAPTER_SUMMARY_MIN_TOKENS
            < self.CODEX_CHAPTER_SUMMARY_MAX_TOKENS
        ):
            raise ValueError("Codex chapter summary token bounds are invalid")
        if not (
            50 <= self.CODEX_CHECKPOINT_SUMMARY_MIN_TOKENS
            < self.CODEX_CHECKPOINT_SUMMARY_MAX_TOKENS
        ):
            raise ValueError("Codex checkpoint summary token bounds are invalid")
        if not (
            50 <= self.CODEX_VOLUME_SUMMARY_MIN_TOKENS
            < self.CODEX_VOLUME_SUMMARY_MAX_TOKENS
        ):
            raise ValueError("Codex volume summary token bounds are invalid")
        if not 0.1 <= self.RRF_SOURCE_QUOTA_RATIO <= 0.5:
            raise ValueError("RRF_SOURCE_QUOTA_RATIO must be between 0.1 and 0.5")
        if not 1 <= self.BM25_PREFIX_CACHE_SIZE <= 32:
            raise ValueError("BM25_PREFIX_CACHE_SIZE must be between 1 and 32")
        for field in ("CODEX_QA_CACHE_VERSION", "CODEX_PROFILE_CACHE_VERSION"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be empty")
        valid_efforts = {"low", "medium", "high", "xhigh", "max"}
        for field in ("OPENAI_CODEX_REASONING_TRANSLATE", "OPENAI_CODEX_REASONING_CODEX"):
            if getattr(self, field) not in valid_efforts:
                raise ValueError(f"{field} has an unsupported value")
        for field in ("OPENAI_CODEX_MODEL_TRANSLATE", "OPENAI_CODEX_MODEL_CODEX"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be empty")
        model_effort_policy = (
            (
                "OPENAI_CODEX_MODEL_TRANSLATE",
                "OPENAI_CODEX_REASONING_TRANSLATE",
            ),
            (
                "OPENAI_CODEX_MODEL_CODEX",
                "OPENAI_CODEX_REASONING_CODEX",
            ),
        )
        for model_field, effort_field in model_effort_policy:
            model = getattr(self, model_field).strip().lower()
            effort = getattr(self, effort_field)
            required_effort = (
                "xhigh"
                if model.endswith(("-luna", "-terra"))
                else None
            )
            if required_effort is not None and effort != required_effort:
                raise ValueError(
                    f"{effort_field} must be {required_effort!r} when "
                    f"{model_field} selects {model!r}"
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
