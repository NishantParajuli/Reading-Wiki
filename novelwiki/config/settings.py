from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # NOTE: asyncpg expects a plain `postgresql://` scheme (NOT the SQLAlchemy
    # `postgresql+asyncpg://` dialect form) — both the pool and the schema
    # bootstrap connect via asyncpg directly.
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/novelwiki"
    DB_SUPERUSER_URL: str = "postgresql://postgres:postgres@localhost:5432/postgres"

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_REFERER: str = "https://github.com/epick/novelwiki"
    OPENROUTER_TITLE: str = "Spoiler-Aware Webnovel Wiki"

    # Presentation metadata for the UI hero/home surface. These are display-only
    # and never gate content — purely the title/blurb the reader sees.
    NOVEL_TITLE: str = "The Codex"
    NOVEL_BLURB: str = "A spoiler-safe wiki for the novel you're reading — every fact bounded to where you are."

    # "Flash reads, Pro thinks" — set these to two distinct models to realize the
    # cost/quality split (e.g. a cheap model for reading/distilling and a stronger
    # one for planning/synthesis). They may legitimately be the same model.
    MODEL_FLASH: str = "deepseek/deepseek-v4-flash"
    MODEL_PRO: str = "deepseek/deepseek-v4-pro"

    # Model used to translate raw (foreign-language) chapters. Point this at your
    # preferred DeepSeek "pro" model on OpenRouter. Used by the Phase 2 translation
    # pipeline (on-demand when a raw chapter is opened, + background prefetch).
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
    RETRIEVE_K: int = 50
    RERANK_TOP_N: int = 8
    MAX_ITERATIONS: int = 5
    BM25_INDEX_PATH: str = "./data/bm25_index"
    # Run BM25's synchronous tokenize/index/search off the event loop (asyncio.to_thread)
    # so a heavy lexical search can't stall unrelated requests. Leave True in prod.
    BM25_THREAD_OFFLOAD: bool = True

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
    # Hard caps on what a model-planned tool call may request, so the LLM can't be steered
    # into a huge fan-out. Applied in the agent's execute_tool dispatcher.
    ASK_TOOL_MAX_K: int = 100                     # clamp hybrid_search k
    ASK_TOOL_MAX_TOP_N: int = 20                  # clamp rerank top_n
    ASK_TOOL_MAX_RERANK_HITS: int = 100           # clamp rerank candidate documents sent to provider
    ASK_TOOL_MAX_QUERY_CHARS: int = 2000          # reject longer model-supplied tool queries
    ASK_MAX_TOOL_CALLS_PER_ITER: int = 4          # tool calls processed per planner iteration

    # ── Extraction accuracy knobs ──
    # The running "story-so-far" summary is rebuilt each chapter from this many
    # leading characters of the chapter. Keep it large enough to cover a whole
    # chapter (an 8k-word chapter is ~44k chars) so late-chapter developments
    # still feed forward; lower it only to trade continuity for cost.
    SUMMARY_INPUT_MAX_CHARS: int = 48000
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

    # Text segmentation/cleanup LLM (routed through OpenRouter alongside the codex models).
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
