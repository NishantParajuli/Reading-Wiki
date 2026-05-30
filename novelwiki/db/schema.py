import asyncpg
import logging
from novelwiki.config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL_QUERIES = [
    # Extensions
    "CREATE EXTENSION IF NOT EXISTS vector;",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
    
    # 1. Chapters
    """
    CREATE TABLE IF NOT EXISTS chapters (
      number      NUMERIC PRIMARY KEY,                 -- canonical chapter index (supports float, e.g. 15.5)
      title       TEXT,
      url         TEXT,
      raw_html    TEXT,
      clean_text  TEXT NOT NULL,
      word_count  INT,
      scraped_at  TIMESTAMPTZ DEFAULT now()
    );
    """,
    
    # 2. Chunks
    f"""
    CREATE TABLE IF NOT EXISTS chunks (
      id          BIGSERIAL PRIMARY KEY,
      chapter     NUMERIC NOT NULL REFERENCES chapters(number) ON DELETE CASCADE,
      chunk_index INT  NOT NULL,
      text        TEXT NOT NULL,
      token_count INT,
      embedding   vector({settings.EMBED_DIM}),    -- dimension == settings.EMBED_DIM
      UNIQUE (chapter, chunk_index)
    );
    """,
    "CREATE INDEX IF NOT EXISTS chunks_chapter_idx ON chunks (chapter);",
    
    # 3. Entities
    f"""
    CREATE TABLE IF NOT EXISTS entities (
      id                 BIGSERIAL PRIMARY KEY,
      canonical_name     TEXT NOT NULL,
      type               TEXT NOT NULL,            -- character|location|faction|item|concept|organization
      description        TEXT,
      name_embedding     vector({settings.EMBED_DIM}),  -- embed "name + description"; dim == settings.EMBED_DIM
      first_seen_chapter NUMERIC NOT NULL,
      created_at         TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS entities_type_idx ON entities (type);",
    "CREATE INDEX IF NOT EXISTS entities_name_trgm ON entities USING gin (canonical_name gin_trgm_ops);",
    
    # 4. Entity aliases
    """
    CREATE TABLE IF NOT EXISTS entity_aliases (
      id                  BIGSERIAL PRIMARY KEY,
      entity_id           BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      alias               TEXT   NOT NULL,
      revealed_at_chapter NUMERIC NOT NULL DEFAULT 0.0,
      UNIQUE (entity_id, alias)
    );
    """,
    "CREATE INDEX IF NOT EXISTS alias_trgm ON entity_aliases USING gin (alias gin_trgm_ops);",
    "CREATE INDEX IF NOT EXISTS alias_reveal_idx ON entity_aliases (revealed_at_chapter);",
    
    # 5. Identity links
    """
    CREATE TABLE IF NOT EXISTS identity_links (
      id                  BIGSERIAL PRIMARY KEY,
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
    "CREATE INDEX IF NOT EXISTS facts_chapter ON entity_facts (chapter);",
    "CREATE INDEX IF NOT EXISTS facts_data_gin ON entity_facts USING gin (data);",
    
    # 7. Relationships
    """
    CREATE TABLE IF NOT EXISTS relationships (
      id              BIGSERIAL PRIMARY KEY,
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
    "CREATE INDEX IF NOT EXISTS rel_chapter ON relationships (chapter);",
    
    # 8. Events
    """
    CREATE TABLE IF NOT EXISTS events (
      id              BIGSERIAL PRIMARY KEY,
      chapter         NUMERIC NOT NULL,
      description     TEXT,
      participants    BIGINT[],                     -- entity ids
      location_id     BIGINT REFERENCES entities(id) ON DELETE SET NULL,
      significance    TEXT,
      data            JSONB,
      source_chunk_ids BIGINT[]
    );
    """,
    "CREATE INDEX IF NOT EXISTS events_chapter ON events (chapter);",
    
    # 9. Extraction state
    """
    CREATE TABLE IF NOT EXISTS extraction_state (
      chapter         NUMERIC PRIMARY KEY,
      running_summary TEXT,                         -- Story-so-far through this chapter
      processed_at    TIMESTAMPTZ DEFAULT now()
    );
    """,
    
    # 10. Wiki cache
    """
    CREATE TABLE IF NOT EXISTS wiki_cache (
      entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter_ceiling NUMERIC NOT NULL,
      rendered_md     TEXT   NOT NULL,
      model           TEXT,
      evidence_ids    JSONB,                        -- {fact_ids:[], chunk_ids:[], rel_ids:[]}
      created_at      TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (entity_id, chapter_ceiling)
    );
    """,
    
    # 11. Query cache
    """
    CREATE TABLE IF NOT EXISTS query_cache (
      id              BIGSERIAL PRIMARY KEY,
      query_hash      TEXT NOT NULL,                -- hash(normalized_question)
      chapter_ceiling NUMERIC NOT NULL,
      answer_md       TEXT,
      evidence_ids    JSONB,
      created_at      TIMESTAMPTZ DEFAULT now(),
      UNIQUE (query_hash, chapter_ceiling)
    );
    """
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
