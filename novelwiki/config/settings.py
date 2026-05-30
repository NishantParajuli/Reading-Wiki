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
