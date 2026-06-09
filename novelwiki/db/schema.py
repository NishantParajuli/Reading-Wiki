import asyncpg
import logging
from novelwiki.config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL_QUERIES = [
    # Extensions
    "CREATE EXTENSION IF NOT EXISTS vector;",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",

    # ── 0. Novels ──────────────────────────────────────────────────────────
    # The library. One row per novel the user is reading. A novel is a single
    # continuous reading sequence even when it is stitched from several sources
    # (e.g. an English site that ends at ch.124 + a raw site that continues at 125).
    """
    CREATE TABLE IF NOT EXISTS novels (
      id                BIGSERIAL PRIMARY KEY,
      title             TEXT NOT NULL,
      author            TEXT,
      cover_url         TEXT,
      description       TEXT,
      original_language TEXT DEFAULT 'en',
      codex_enabled     BOOLEAN DEFAULT FALSE,        -- opt-in spoiler-safe codex pipeline
      created_at        TIMESTAMPTZ DEFAULT now(),
      updated_at        TIMESTAMPTZ DEFAULT now()
    );
    """,

    # ── 0b. Sources ────────────────────────────────────────────────────────
    # A novel can have several sources, each scraped by a different adapter. This
    # is what makes scraping dynamic per-site: the `adapter` key selects the
    # technique (the dropdown choice) and `config` holds per-source knobs (e.g.
    # CSS selectors for the generic adapter). `chapter_offset` maps a source's
    # local chapter numbering onto the novel's GLOBAL numbering so multiple
    # sources line up into one continuous sequence.
    """
    CREATE TABLE IF NOT EXISTS sources (
      id              BIGSERIAL PRIMARY KEY,
      novel_id        BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      adapter         TEXT NOT NULL,                  -- registry key: fenrirealm|generic|...
      start_url       TEXT,                           -- or file path for epub/pdf later
      config          JSONB,                          -- per-source adapter config
      language        TEXT DEFAULT 'en',
      is_raw          BOOLEAN DEFAULT FALSE,           -- needs translation
      chapter_offset  NUMERIC DEFAULT 0,              -- source-local number + offset = global number
      label           TEXT,
      last_scraped_at TIMESTAMPTZ,
      created_at      TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS sources_novel_idx ON sources (novel_id);",

    # ── 1. Chapters ────────────────────────────────────────────────────────
    # `number` is the GLOBAL canonical reading index (supports float, e.g. 15.5)
    # and remains the value compared against the spoiler ceiling everywhere.
    # `content` is the readable text shown in the reader: the English content for
    # eng sources, or the translation for raw sources. `original_text` keeps the
    # source-language text for raw sources so re-translation never needs a re-scrape.
    """
    CREATE TABLE IF NOT EXISTS chapters (
      novel_id           BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      number             NUMERIC NOT NULL,
      source_id          BIGINT  REFERENCES sources(id) ON DELETE SET NULL,
      title              TEXT,
      url                TEXT,
      raw_html           TEXT,
      original_text      TEXT,                         -- cleaned text in source language (raw sources)
      content            TEXT,                         -- readable text shown in reader (eng or translation)
      language           TEXT,
      is_translated      BOOLEAN DEFAULT FALSE,
      translation_status TEXT DEFAULT 'none',          -- none|pending|done|failed
      translation_model  TEXT,
      word_count         INT,
      scraped_at         TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (novel_id, number)
    );
    """,
    "CREATE INDEX IF NOT EXISTS chapters_source_idx ON chapters (source_id);",

    # ── 2. Chunks ──────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS chunks (
      id          BIGSERIAL PRIMARY KEY,
      novel_id    BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter     NUMERIC NOT NULL,
      chunk_index INT  NOT NULL,
      text        TEXT NOT NULL,
      token_count INT,
      embedding   vector({embed_dim}),               -- dimension == settings.EMBED_DIM
      UNIQUE (novel_id, chapter, chunk_index),
      FOREIGN KEY (novel_id, chapter) REFERENCES chapters(novel_id, number) ON DELETE CASCADE
    );
    """.format(embed_dim=settings.EMBED_DIM),
    "CREATE INDEX IF NOT EXISTS chunks_chapter_idx ON chunks (novel_id, chapter);",

    # ── 3. Entities ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS entities (
      id                 BIGSERIAL PRIMARY KEY,
      novel_id           BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      canonical_name     TEXT NOT NULL,
      type               TEXT NOT NULL,            -- character|location|faction|item|concept|organization
      description        TEXT,
      name_embedding     vector({embed_dim}),      -- embed "name + description"; dim == settings.EMBED_DIM
      first_seen_chapter NUMERIC NOT NULL,
      created_at         TIMESTAMPTZ DEFAULT now()
    );
    """.format(embed_dim=settings.EMBED_DIM),
    "CREATE INDEX IF NOT EXISTS entities_novel_type_idx ON entities (novel_id, type);",
    "CREATE INDEX IF NOT EXISTS entities_name_trgm ON entities USING gin (canonical_name gin_trgm_ops);",

    # 3b. Entity descriptions (spoiler-safe, per-chapter history)
    """
    CREATE TABLE IF NOT EXISTS entity_descriptions (
      id          BIGSERIAL PRIMARY KEY,
      novel_id    BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_id   BIGINT  NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter     NUMERIC NOT NULL,            -- chapter this description was observed in (spoiler key)
      description TEXT    NOT NULL,
      created_at  TIMESTAMPTZ DEFAULT now(),
      UNIQUE (entity_id, chapter)              -- at most one description per entity per chapter
    );
    """,
    "CREATE INDEX IF NOT EXISTS entity_desc_entity_chapter ON entity_descriptions (entity_id, chapter);",

    # 4. Entity aliases
    """
    CREATE TABLE IF NOT EXISTS entity_aliases (
      id                  BIGSERIAL PRIMARY KEY,
      novel_id            BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_id           BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      alias               TEXT   NOT NULL,
      revealed_at_chapter NUMERIC NOT NULL DEFAULT 0.0,
      UNIQUE (entity_id, alias)
    );
    """,
    "CREATE INDEX IF NOT EXISTS alias_trgm ON entity_aliases USING gin (alias gin_trgm_ops);",
    "CREATE INDEX IF NOT EXISTS alias_reveal_idx ON entity_aliases (novel_id, revealed_at_chapter);",

    # 5. Identity links
    """
    CREATE TABLE IF NOT EXISTS identity_links (
      id                  BIGSERIAL PRIMARY KEY,
      novel_id            BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_a            BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      entity_b            BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      revealed_at_chapter NUMERIC NOT NULL,
      note                TEXT
    );
    """,

    # 6. Entity facts
    """
    CREATE TABLE IF NOT EXISTS entity_facts (
      id              BIGSERIAL PRIMARY KEY,
      novel_id        BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter         NUMERIC NOT NULL,             -- The spoiler key
      fact_type       TEXT,                        -- trait|status|backstory|action|location|possession|belief|...
      content         TEXT   NOT NULL,             -- natural-language fact as known at this chapter
      data            JSONB,                       -- flexible structured payload
      source_chunk_ids BIGINT[],                   -- provenance
      created_at      TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS facts_entity_chapter ON entity_facts (entity_id, chapter);",
    "CREATE INDEX IF NOT EXISTS facts_chapter ON entity_facts (novel_id, chapter);",
    "CREATE INDEX IF NOT EXISTS facts_data_gin ON entity_facts USING gin (data);",

    # 7. Relationships
    """
    CREATE TABLE IF NOT EXISTS relationships (
      id              BIGSERIAL PRIMARY KEY,
      novel_id        BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      source_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      target_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter         NUMERIC NOT NULL,
      relation_type   TEXT,                         -- mentor|ally|enemy|family|romantic|rival|subordinate|...
      directed        BOOLEAN DEFAULT TRUE,
      content         TEXT,
      data            JSONB,
      source_chunk_ids BIGINT[]
    );
    """,
    "CREATE INDEX IF NOT EXISTS rel_source ON relationships (source_id, chapter);",
    "CREATE INDEX IF NOT EXISTS rel_target ON relationships (target_id, chapter);",
    "CREATE INDEX IF NOT EXISTS rel_chapter ON relationships (novel_id, chapter);",

    # 8. Events
    """
    CREATE TABLE IF NOT EXISTS events (
      id              BIGSERIAL PRIMARY KEY,
      novel_id        BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter         NUMERIC NOT NULL,
      description     TEXT,
      participants    BIGINT[],                     -- entity ids
      location_id     BIGINT REFERENCES entities(id) ON DELETE SET NULL,
      significance    TEXT,
      data            JSONB,
      source_chunk_ids BIGINT[]
    );
    """,
    "CREATE INDEX IF NOT EXISTS events_chapter ON events (novel_id, chapter);",

    # 9. Extraction state
    """
    CREATE TABLE IF NOT EXISTS extraction_state (
      novel_id        BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter         NUMERIC NOT NULL,
      running_summary TEXT,                         -- Story-so-far through this chapter
      processed_at    TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (novel_id, chapter)
    );
    """,

    # 10. Wiki cache
    """
    CREATE TABLE IF NOT EXISTS wiki_cache (
      novel_id        BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter_ceiling NUMERIC NOT NULL,
      rendered_md     TEXT   NOT NULL,
      model           TEXT,
      evidence_ids    JSONB,                        -- {fact_ids:[], chunk_ids:[], rel_ids:[]}
      created_at      TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (novel_id, entity_id, chapter_ceiling)
    );
    """,

    # 11. Query cache
    """
    CREATE TABLE IF NOT EXISTS query_cache (
      id              BIGSERIAL PRIMARY KEY,
      novel_id        BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      query_hash      TEXT NOT NULL,                -- hash(normalized_question)
      chapter_ceiling NUMERIC NOT NULL,
      answer_md       TEXT,
      evidence_ids    JSONB,
      created_at      TIMESTAMPTZ DEFAULT now(),
      UNIQUE (novel_id, query_hash, chapter_ceiling)
    );
    """,

    # ── 12. Reading progress ───────────────────────────────────────────────
    # Single-user app: one row per novel. `max_chapter_read` drives the codex
    # spoiler ceiling; `last_chapter` + `scroll_pct` drive "continue reading".
    """
    CREATE TABLE IF NOT EXISTS reading_progress (
      novel_id         BIGINT PRIMARY KEY REFERENCES novels(id) ON DELETE CASCADE,
      last_chapter     NUMERIC,
      max_chapter_read NUMERIC,
      scroll_pct       REAL DEFAULT 0,
      updated_at       TIMESTAMPTZ DEFAULT now()
    );
    """,

    # ── 13. Bookmarks ──────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS bookmarks (
      id          BIGSERIAL PRIMARY KEY,
      novel_id    BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter     NUMERIC NOT NULL,
      note        TEXT,
      created_at  TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS bookmarks_novel_idx ON bookmarks (novel_id, chapter);",

    # ── 14. Translation glossary ───────────────────────────────────────────
    # Per-novel name/term consistency anchor for translation. `locked` rows are
    # user-pinned canonical renderings the auto-glossary never overwrites.
    """
    CREATE TABLE IF NOT EXISTS translation_glossary (
      id          BIGSERIAL PRIMARY KEY,
      novel_id    BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      source_term TEXT NOT NULL,                    -- original language term, e.g. 林轩
      translation TEXT NOT NULL,                    -- canonical English rendering, e.g. Lin Xuan
      term_type   TEXT,                             -- name|place|skill|item|term
      notes       TEXT,
      locked      BOOLEAN DEFAULT FALSE,
      created_at  TIMESTAMPTZ DEFAULT now(),
      UNIQUE (novel_id, source_term)
    );
    """,
    "CREATE INDEX IF NOT EXISTS glossary_novel_idx ON translation_glossary (novel_id, term_type);",
]

# Tables in dependency order (children first) — used by reset_db to drop cleanly.
ALL_TABLES = [
    "translation_glossary",
    "bookmarks",
    "reading_progress",
    "query_cache",
    "wiki_cache",
    "extraction_state",
    "events",
    "relationships",
    "entity_facts",
    "identity_links",
    "entity_aliases",
    "entity_descriptions",
    "entities",
    "chunks",
    "chapters",
    "sources",
    "novels",
]


async def init_database():
    # 1. Connect to superuser DB to ensure database exists
    try:
        conn = await asyncpg.connect(settings.DB_SUPERUSER_URL)
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = $1);",
            "novelwiki"
        )
        if not exists:
            logger.info("Database 'novelwiki' does not exist. Creating...")
            await conn.execute("CREATE DATABASE novelwiki;")
            logger.info("Database 'novelwiki' created successfully.")
        await conn.close()
    except Exception as e:
        logger.warning(f"Could not check/create database using superuser URL: {e}")

    # 2. Connect to the 'novelwiki' database and apply schema
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL)
        logger.info("Applying migrations and DDL queries to 'novelwiki'...")

        # Build the active query list (only apply HNSW index if EMBED_DIM <= 2000)
        active_queries = list(DDL_QUERIES)
        if settings.EMBED_DIM <= 2000:
            active_queries.append("CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);")
            active_queries.append("CREATE INDEX IF NOT EXISTS entities_name_emb ON entities USING hnsw (name_embedding vector_cosine_ops);")
        else:
            logger.warning(
                f"EMBED_DIM ({settings.EMBED_DIM}) exceeds pgvector HNSW limits (2000 dimensions). "
                f"Bypassing HNSW index creation. Raw scanning will be used, which is highly efficient for webnovel scale."
            )

        for query in active_queries:
            try:
                await conn.execute(query)
            except Exception as ex:
                logger.error(f"Error executing schema query:\n{query.strip()}\nError: {ex}")
                raise ex
        logger.info("Database schema initialized and vector/trigram indexes are live.")
        await conn.close()
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        raise e

if __name__ == "__main__":
    import asyncio
    asyncio.run(init_database())
