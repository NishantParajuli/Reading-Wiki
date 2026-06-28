import asyncpg
import logging
from novelwiki.config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DDL_QUERIES = [
    # Extensions
    "CREATE EXTENSION IF NOT EXISTS vector;",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm;",

    # Durable one-time migration markers. This prevents guarded data migrations from
    # reinterpreting valid post-migration rows (for example ownerless novels after a
    # user delete) as legacy single-user data on a later restart.
    """
    CREATE TABLE IF NOT EXISTS app_migrations (
      name       TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ DEFAULT now(),
      details    JSONB DEFAULT '{}'
    );
    """,

    # ══ Multi-user layer ═══════════════════════════════════════════════════
    # Accounts. One row per human. `password_hash` is NULL for OAuth-only logins.
    # `role` gates the admin surface; `status` lets an admin suspend/ban without
    # deleting data. Per-user spend caps default to settings when NULL. `prefs`
    # holds reader preferences synced across devices (was browser localStorage).
    """
    CREATE TABLE IF NOT EXISTS users (
      id                        BIGSERIAL PRIMARY KEY,
      email                     TEXT UNIQUE NOT NULL,          -- stored lowercased
      email_verified            BOOLEAN DEFAULT FALSE,
      password_hash             TEXT,                          -- NULL for OAuth-only
      username                  TEXT UNIQUE NOT NULL,          -- handle for /u/<username>
      display_name              TEXT,
      bio                       TEXT,
      avatar_path               TEXT,                          -- relative under ASSET_DIR/_users/<id>/
      role                      TEXT DEFAULT 'user',           -- user|admin
      status                    TEXT DEFAULT 'active',         -- active|suspended|banned
      quota_translated_chapters INT,                           -- NULL ⇒ settings default
      quota_ocr_pages           INT,
      quota_codex_builds        INT,
      prefs                     JSONB DEFAULT '{}',
      created_at                TIMESTAMPTZ DEFAULT now(),
      updated_at                TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS users_username_idx ON users (username);",

    # External identity links (Google/Discord). A user may link several providers.
    """
    CREATE TABLE IF NOT EXISTS oauth_accounts (
      id                  BIGSERIAL PRIMARY KEY,
      user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      provider            TEXT NOT NULL,                       -- google|discord
      provider_account_id TEXT NOT NULL,
      created_at          TIMESTAMPTZ DEFAULT now(),
      UNIQUE (provider, provider_account_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS oauth_user_idx ON oauth_accounts (user_id);",

    # Server-side sessions. The cookie carries an opaque token; we store only its
    # hash. Deleting the row (logout / ban) revokes access immediately.
    """
    CREATE TABLE IF NOT EXISTS sessions (
      token_hash   TEXT PRIMARY KEY,
      user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at   TIMESTAMPTZ DEFAULT now(),
      expires_at   TIMESTAMPTZ NOT NULL,
      last_seen_at TIMESTAMPTZ DEFAULT now(),
      user_agent   TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);",

    # One-time email tokens for verification + password reset (hashed at rest).
    """
    CREATE TABLE IF NOT EXISTS email_tokens (
      id         BIGSERIAL PRIMARY KEY,
      user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind       TEXT NOT NULL,                                -- verify|reset
      token_hash TEXT UNIQUE NOT NULL,
      expires_at TIMESTAMPTZ NOT NULL,
      used_at    TIMESTAMPTZ,
      created_at TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS email_tokens_user_idx ON email_tokens (user_id, kind);",

    # NOTE: `library_entries` references novels(id) and is defined just after the
    # novels table below (sequential DDL — the referenced table must exist first).

    # Monthly per-user spend meter (one row per user per month bucket).
    """
    CREATE TABLE IF NOT EXISTS quota_usage (
      user_id            BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      period             DATE NOT NULL,                        -- first-of-month bucket
      translated_chapters INT NOT NULL DEFAULT 0,
      ocr_pages          INT NOT NULL DEFAULT 0,
      codex_builds       INT NOT NULL DEFAULT 0,
      PRIMARY KEY (user_id, period)
    );
    """,

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
      shelf             TEXT,                          -- legacy/owner default; per-user shelf lives in library_entries
      status_tags       TEXT[] DEFAULT '{}',           -- legacy/owner default; per-user tags live in library_entries
      owner_id          BIGINT REFERENCES users(id) ON DELETE SET NULL,   -- who uploaded it (NULL = system/global)
      visibility        TEXT DEFAULT 'private',        -- private|public|global
      contribution_policy TEXT DEFAULT 'manual',       -- manual|auto: how contribute-back offers merge
      created_at        TIMESTAMPTZ DEFAULT now(),
      updated_at        TIMESTAMPTZ DEFAULT now()
    );
    """,
    # Idempotent backfills so an existing live DB gains the new columns without a
    # destructive reset (CREATE TABLE IF NOT EXISTS won't add columns to an old table).
    "ALTER TABLE novels ADD COLUMN IF NOT EXISTS shelf TEXT;",
    "ALTER TABLE novels ADD COLUMN IF NOT EXISTS status_tags TEXT[] DEFAULT '{}';",
    "CREATE INDEX IF NOT EXISTS novels_shelf_idx ON novels (shelf);",
    # File-import series grouping: when several EPUB volumes of one series are imported,
    # they become sources of a single novel whose `series` records the collection name, so a
    # later volume of the same series auto-appends instead of creating a duplicate novel.
    "ALTER TABLE novels ADD COLUMN IF NOT EXISTS series TEXT;",
    "CREATE INDEX IF NOT EXISTS novels_series_idx ON novels (series);",
    # Multi-user ownership + visibility (idempotent backfills for an existing DB).
    "ALTER TABLE novels ADD COLUMN IF NOT EXISTS owner_id BIGINT REFERENCES users(id) ON DELETE SET NULL;",
    "ALTER TABLE novels ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'private';",
    "ALTER TABLE novels ADD COLUMN IF NOT EXISTS contribution_policy TEXT DEFAULT 'manual';",
    "CREATE INDEX IF NOT EXISTS novels_owner_idx ON novels (owner_id);",
    "CREATE INDEX IF NOT EXISTS novels_visibility_idx ON novels (visibility);",

    # A user's personal library + per-user curation. Adding a shared (global/public)
    # novel here is the "read the shared copy" action — one shared text, many readers.
    # Defined here (not in the multi-user block above) because it references novels(id).
    """
    CREATE TABLE IF NOT EXISTS library_entries (
      id          BIGSERIAL PRIMARY KEY,
      user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      novel_id    BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      shelf       TEXT,                                        -- to_read|reading|completed
      status_tags TEXT[] DEFAULT '{}',
      added_at    TIMESTAMPTZ DEFAULT now(),
      UNIQUE (user_id, novel_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS library_user_idx ON library_entries (user_id);",

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
      adapter         TEXT NOT NULL,                  -- registry key: fenrirealm|readhive|...
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
      content_version    INT DEFAULT 1,                -- bumped on each base-content change; anchor for per-user overlay merge
      scraped_at         TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (novel_id, number)
    );
    """,
    "CREATE INDEX IF NOT EXISTS chapters_source_idx ON chapters (source_id);",
    # File-import additions: `kind` marks non-chapter sections (chapter|frontmatter|
    # interlude|backmatter) so the reader can flag/skip them; `part_label` groups chapters
    # under a "Volume 1" heading in the TOC. Idempotent backfills for an existing DB.
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'chapter';",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS part_label TEXT;",
    # Multi-user: content version anchor for translation overlays (Phase 5).
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS content_version INT DEFAULT 1;",

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
    # Per-user, per-novel. `max_chapter_read` drives that user's codex spoiler
    # ceiling; `last_chapter` + `scroll_pct` drive "continue reading". On a fresh DB
    # the PK is composite; an existing single-user DB (PK = novel_id) is migrated to
    # this shape by novelwiki/db/migrate_multiuser.py.
    """
    CREATE TABLE IF NOT EXISTS reading_progress (
      user_id          BIGINT REFERENCES users(id) ON DELETE CASCADE,
      novel_id         BIGINT REFERENCES novels(id) ON DELETE CASCADE,
      last_chapter     NUMERIC,
      max_chapter_read NUMERIC,
      scroll_pct       REAL DEFAULT 0,
      updated_at       TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (user_id, novel_id)
    );
    """,
    # Existing single-user DBs gain the column here; the PK swap is done in the migration.
    "ALTER TABLE reading_progress ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;",

    # ── 13. Bookmarks ──────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS bookmarks (
      id          BIGSERIAL PRIMARY KEY,
      user_id     BIGINT  REFERENCES users(id) ON DELETE CASCADE,
      novel_id    BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter     NUMERIC NOT NULL,
      note        TEXT,
      created_at  TIMESTAMPTZ DEFAULT now()
    );
    """,
    "ALTER TABLE bookmarks ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;",
    "CREATE INDEX IF NOT EXISTS bookmarks_user_novel_idx ON bookmarks (user_id, novel_id, chapter);",

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

    # ── 15. Assets ─────────────────────────────────────────────────────────
    # Extracted images from file imports (EPUB/PDF): covers, inline illustrations,
    # page scans. Heavy bytes live on disk under ASSET_DIR/<novel_id>/; this row is
    # the pointer. `sha256` content-addresses the bytes so the same image shared
    # across chapters is stored once (UNIQUE per novel).
    """
    CREATE TABLE IF NOT EXISTS assets (
      id         BIGSERIAL PRIMARY KEY,
      novel_id   BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      sha256     TEXT NOT NULL,
      path       TEXT NOT NULL,                 -- relative under ASSET_DIR/<novel_id>/
      mime       TEXT,
      kind       TEXT,                          -- cover|illustration|page_scan
      width      INT, height INT,
      created_at TIMESTAMPTZ DEFAULT now(),
      UNIQUE (novel_id, sha256)                 -- content dedup
    );
    """,
    "CREATE INDEX IF NOT EXISTS assets_novel_idx ON assets (novel_id);",

    # ── 16. Import jobs ────────────────────────────────────────────────────
    # Durable, resumable ingestion pipeline state for an uploaded EPUB/PDF. The big
    # artifacts (block stream, original blob, images) live on disk; this row holds the
    # job status + the (small) editable segmentation `plan` the user reviews before
    # committing chapters. A DB-polled worker advances these across restarts.
    """
    CREATE TABLE IF NOT EXISTS import_jobs (
      id            BIGSERIAL PRIMARY KEY,
      novel_id      BIGINT REFERENCES novels(id) ON DELETE CASCADE,    -- null until target chosen/created
      source_id     BIGINT REFERENCES sources(id) ON DELETE SET NULL,
      format        TEXT NOT NULL,                                     -- epub|pdf
      original_path TEXT NOT NULL,
      file_sha256   TEXT,
      status        TEXT NOT NULL DEFAULT 'uploaded',
      stage         TEXT,                                              -- human-readable current step
      detected_meta JSONB DEFAULT '{}',
      plan          JSONB,                                             -- editable draft segmentation plan
      stats         JSONB DEFAULT '{}',
      cost_estimate JSONB,
      progress      JSONB DEFAULT '{}',                                -- {done,total,unit}
      options       JSONB DEFAULT '{}',                                -- {gemini_first:bool, target:new|append, ...}
      error         TEXT,
      user_id       BIGINT REFERENCES users(id) ON DELETE CASCADE,     -- who uploaded the file
      created_at    TIMESTAMPTZ DEFAULT now(),
      updated_at    TIMESTAMPTZ DEFAULT now()
    );
    """,
    "ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(id) ON DELETE CASCADE;",
    "CREATE INDEX IF NOT EXISTS import_jobs_status_idx ON import_jobs (status);",
    "CREATE INDEX IF NOT EXISTS import_jobs_user_idx ON import_jobs (user_id);",

    # ── 17. Provider budget ────────────────────────────────────────────────
    # Daily provider call counter (Gemini free-tier guard) that survives restarts, so a
    # multi-day OCR run never blows past the free quota. One row per (provider, day).
    """
    CREATE TABLE IF NOT EXISTS provider_budget (
      provider TEXT NOT NULL,
      day      DATE NOT NULL,
      used     INT  NOT NULL DEFAULT 0,
      PRIMARY KEY (provider, day)
    );
    """,

    # ── 18. Chapter overlays (Phase 5) ─────────────────────────────────────
    # Per-user translation override on top of a shared novel's base content. The
    # reader shows the overlay if present, else chapters.content. `base_version`
    # records the chapters.content_version it forked from, so a later base change
    # can be detected as a merge conflict.
    """
    CREATE TABLE IF NOT EXISTS chapter_overlays (
      id           BIGSERIAL PRIMARY KEY,
      user_id      BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      novel_id     BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter      NUMERIC NOT NULL,
      content      TEXT    NOT NULL,
      base_version INT     NOT NULL DEFAULT 1,
      origin       TEXT    DEFAULT 'manual_edit',              -- manual_edit|self_translated
      conflict     BOOLEAN DEFAULT FALSE,
      created_at   TIMESTAMPTZ DEFAULT now(),
      updated_at   TIMESTAMPTZ DEFAULT now(),
      UNIQUE (user_id, novel_id, chapter)
    );
    """,
    "CREATE INDEX IF NOT EXISTS overlays_user_novel_idx ON chapter_overlays (user_id, novel_id);",

    # ── 19. Contributions (Phase 5) ────────────────────────────────────────
    # Contribute-back "pull requests": a user offers their overlay to the novel
    # owner (admin for global, uploader for public) to merge into the shared base.
    """
    CREATE TABLE IF NOT EXISTS contributions (
      id           BIGSERIAL PRIMARY KEY,
      novel_id     BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      from_user_id BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind         TEXT    DEFAULT 'translation',
      chapter      NUMERIC NOT NULL,
      content      TEXT    NOT NULL,
      base_version INT     NOT NULL DEFAULT 1,
      status       TEXT    DEFAULT 'pending',                 -- pending|accepted|rejected|auto_merged
      reviewed_by  BIGINT  REFERENCES users(id) ON DELETE SET NULL,
      created_at   TIMESTAMPTZ DEFAULT now(),
      reviewed_at  TIMESTAMPTZ
    );
    """,
    "CREATE INDEX IF NOT EXISTS contributions_novel_status_idx ON contributions (novel_id, status);",
]

# Tables in dependency order (children first) — used by reset_db to drop cleanly.
ALL_TABLES = [
    "contributions",
    "chapter_overlays",
    "import_jobs",
    "provider_budget",
    "assets",
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
    "library_entries",
    "sources",
    "novels",
    "quota_usage",
    "email_tokens",
    "sessions",
    "oauth_accounts",
    "users",
    "app_migrations",
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
