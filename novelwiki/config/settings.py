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
    MODEL_FLASH: str = "deepseek/deepseek-chat"
    MODEL_PRO: str = "deepseek/deepseek-chat"

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
    # The "generic" adapter reads the CSS selectors below from config so a new
    # site can be supported without writing code.
    SCRAPER_ADAPTER: str = "fenrirealm"
    SCRAPER_BASE_URL: str = "https://fenrirealm.com"
    SCRAPER_DELAY: float = 1.0
    SCRAPER_TITLE_SELECTOR: str = "h1"
    SCRAPER_CONTENT_SELECTOR: str = "article"
    SCRAPER_NEXT_SELECTOR: str = "a[rel=next]"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
