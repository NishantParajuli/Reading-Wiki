import asyncpg
import logging
from urllib.parse import urlparse

from novelwiki.config.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/") or "novelwiki"


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'

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

    # Admin-owned AGY entitlement.  Reader prefs are intentionally not part of
    # this trust boundary: no row means API-only, and only admin routes mutate it.
    """
    CREATE TABLE IF NOT EXISTS user_ai_backend_policies (
      user_id                 BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      agy_enabled             BOOLEAN NOT NULL DEFAULT FALSE,
      default_backend         TEXT NOT NULL DEFAULT 'api'
                              CHECK (default_backend IN ('api', 'agy')),
      agy_workloads           TEXT[] NOT NULL DEFAULT '{}',
      fallback_to_api         BOOLEAN NOT NULL DEFAULT FALSE,
      max_concurrent_agy_jobs SMALLINT NOT NULL DEFAULT 1
                              CHECK (max_concurrent_agy_jobs BETWEEN 1 AND 4),
      policy_version          BIGINT NOT NULL DEFAULT 1,
      notes                   TEXT,
      granted_by              BIGINT REFERENCES users(id) ON DELETE SET NULL,
      created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK (agy_workloads <@ ARRAY[
        'translate_batch', 'codex_extract', 'segment_import', 'ocr_pages',
        'ask', 'profile_synthesis'
      ]::TEXT[]),
      CHECK (agy_enabled OR default_backend = 'api')
    );
    """,
    "CREATE INDEX IF NOT EXISTS user_ai_backend_policies_enabled_idx "
    "ON user_ai_backend_policies (agy_enabled) WHERE agy_enabled = TRUE;",

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

    # Durable fixed-window counters for auth abuse controls. Bucket keys include
    # only scoped hashes for account/email/token values, not raw identifiers.
    """
    CREATE TABLE IF NOT EXISTS auth_rate_limits (
      bucket_key TEXT PRIMARY KEY,
      count      INT NOT NULL,
      reset_at   TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS auth_rate_limits_reset_idx ON auth_rate_limits (reset_at);",

    # Short-lived concurrency slots for read-side AI (denial-of-wallet control). One row per
    # in-flight uncached AI request (/ask, entity-profile synthesis); rows are self-expiring
    # (expires_at) so a crashed request can't hold a slot forever. See novelwiki/ai_limits.py.
    """
    CREATE TABLE IF NOT EXISTS ai_request_locks (
      id         BIGSERIAL PRIMARY KEY,
      user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      kind       TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS ai_request_locks_user_idx ON ai_request_locks (user_id, kind);",
    "CREATE INDEX IF NOT EXISTS ai_request_locks_expires_idx ON ai_request_locks (expires_at);",

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
      tts_chapters       INT NOT NULL DEFAULT 0,
      PRIMARY KEY (user_id, period)
    );
    """,
    # Idempotent backfills so an existing live DB gains the new quota kind / per-user override.
    "ALTER TABLE quota_usage ADD COLUMN IF NOT EXISTS tts_chapters INT NOT NULL DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_tts_chapters INT;",

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
    # AGY staging/commit identity.  The run id keeps a crashed/retried batch from
    # resetting or committing a chapter staged by another process.
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS translation_run_id UUID;",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS translation_source_sha256 TEXT;",

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

    # ── Codex bounded-memory v2 (additive; v1 rows remain readable) ───────
    """
    CREATE TABLE IF NOT EXISTS chapter_summaries (
      novel_id         BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter          NUMERIC NOT NULL,
      summary          TEXT    NOT NULL,
      token_count      INT     NOT NULL DEFAULT 0,
      source_sha256    TEXT    NOT NULL,
      evidence_chunk_ids BIGINT[] NOT NULL DEFAULT '{}',
      pipeline_version TEXT    NOT NULL,
      model_label      TEXT,
      run_id           UUID,
      created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (novel_id, chapter, pipeline_version),
      CHECK (length(source_sha256)=64),
      FOREIGN KEY (novel_id, chapter) REFERENCES chapters(novel_id, number) ON DELETE CASCADE
    );
    """,
    "CREATE INDEX IF NOT EXISTS chapter_summaries_range_idx ON chapter_summaries "
    "(novel_id, pipeline_version, chapter);",

    """
    CREATE TABLE IF NOT EXISTS memory_segments (
      id               BIGSERIAL PRIMARY KEY,
      novel_id         BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      kind             TEXT    NOT NULL CHECK (kind IN ('checkpoint','volume')),
      start_chapter    NUMERIC NOT NULL,
      end_chapter      NUMERIC NOT NULL,
      through_chapter  NUMERIC NOT NULL,
      part_label       TEXT,
      summary          TEXT    NOT NULL,
      token_count      INT     NOT NULL DEFAULT 0,
      source_hash      TEXT    NOT NULL,
      evidence         JSONB   NOT NULL DEFAULT '{}',
      pipeline_version TEXT    NOT NULL,
      model_label      TEXT,
      run_id           UUID,
      created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE (novel_id, kind, start_chapter, end_chapter, through_chapter, pipeline_version),
      CHECK (start_chapter <= through_chapter AND through_chapter = end_chapter),
      CHECK (length(source_hash)=64),
      CHECK (kind <> 'volume' OR (part_label IS NOT NULL AND length(btrim(part_label))>0))
    );
    """,
    "CREATE INDEX IF NOT EXISTS memory_segments_ceiling_idx ON memory_segments "
    "(novel_id, pipeline_version, kind, through_chapter);",

    """
    CREATE TABLE IF NOT EXISTS entity_activity (
      novel_id         BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_id        BIGINT  NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter          NUMERIC NOT NULL,
      mention_count    INT     NOT NULL DEFAULT 0,
      claim_count      INT     NOT NULL DEFAULT 0,
      event_count      INT     NOT NULL DEFAULT 0,
      salience         REAL    NOT NULL DEFAULT 0,
      source_chunk_ids BIGINT[] NOT NULL DEFAULT '{}',
      pipeline_version TEXT    NOT NULL,
      PRIMARY KEY (novel_id, entity_id, chapter, pipeline_version)
    );
    """,
    "CREATE INDEX IF NOT EXISTS entity_activity_recent_idx ON entity_activity "
    "(novel_id, pipeline_version, chapter DESC, entity_id);",
    "CREATE INDEX IF NOT EXISTS entity_activity_entity_idx ON entity_activity "
    "(novel_id, entity_id, pipeline_version, chapter DESC);",

    """
    CREATE TABLE IF NOT EXISTS entity_state_transitions (
      id                    BIGSERIAL PRIMARY KEY,
      novel_id              BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_id             BIGINT  NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter               NUMERIC NOT NULL,
      state_key             TEXT    NOT NULL,
      operation             TEXT    NOT NULL CHECK (operation IN ('set','clear','add','remove','confirm','contradict')),
      value                 JSONB,
      perspective_entity_id BIGINT REFERENCES entities(id) ON DELETE SET NULL,
      certainty             TEXT    NOT NULL DEFAULT 'confirmed' CHECK (certainty IN ('uncertain','alleged','presumed','confirmed','contradicted')),
      narrative_scope       TEXT    NOT NULL DEFAULT 'current' CHECK (narrative_scope IN ('current','historical','dream','prophecy','alternate')),
      supersedes_id         BIGINT REFERENCES entity_state_transitions(id) ON DELETE SET NULL,
      source_chunk_ids      BIGINT[] NOT NULL,
      pipeline_version      TEXT    NOT NULL,
      run_id                UUID,
      created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS entity_state_lookup_idx ON entity_state_transitions "
    "(novel_id, pipeline_version, entity_id, state_key, chapter, id);",
    "CREATE INDEX IF NOT EXISTS entity_state_chapter_idx ON entity_state_transitions "
    "(novel_id, pipeline_version, chapter);",

    """
    CREATE TABLE IF NOT EXISTS relationship_state_transitions (
      id               BIGSERIAL PRIMARY KEY,
      novel_id         BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      source_id        BIGINT  NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      target_id        BIGINT  NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter          NUMERIC NOT NULL,
      state_key        TEXT    NOT NULL,
      operation        TEXT    NOT NULL CHECK (operation IN ('set','clear','add','remove','confirm','contradict')),
      value            JSONB,
      certainty        TEXT    NOT NULL DEFAULT 'confirmed' CHECK (certainty IN ('uncertain','alleged','presumed','confirmed','contradicted')),
      source_chunk_ids BIGINT[] NOT NULL,
      pipeline_version TEXT    NOT NULL,
      run_id           UUID,
      created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS relationship_state_lookup_idx ON relationship_state_transitions "
    "(novel_id, pipeline_version, source_id, target_id, state_key, chapter, id);",
    "CREATE INDEX IF NOT EXISTS relationship_state_chapter_idx ON relationship_state_transitions "
    "(novel_id, pipeline_version, chapter);",

    """
    CREATE TABLE IF NOT EXISTS plot_threads (
      id                    BIGSERIAL PRIMARY KEY,
      novel_id              BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      stable_title          TEXT    NOT NULL,
      introduced_at_chapter NUMERIC NOT NULL,
      pipeline_version      TEXT    NOT NULL,
      created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "ALTER TABLE plot_threads ADD COLUMN IF NOT EXISTS pipeline_version TEXT NOT NULL DEFAULT '1.0';",
    "CREATE INDEX IF NOT EXISTS plot_threads_title_trgm ON plot_threads USING gin (stable_title gin_trgm_ops);",
    "CREATE INDEX IF NOT EXISTS plot_threads_novel_idx ON plot_threads "
    "(novel_id, pipeline_version, introduced_at_chapter);",

    """
    CREATE TABLE IF NOT EXISTS plot_thread_updates (
      id               BIGSERIAL PRIMARY KEY,
      novel_id         BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      thread_id        BIGINT  NOT NULL REFERENCES plot_threads(id) ON DELETE CASCADE,
      chapter          NUMERIC NOT NULL,
      operation        TEXT    NOT NULL CHECK (operation IN ('open','advance','clarify','resolve','reopen','mark_dormant','contradict')),
      summary          TEXT    NOT NULL,
      participants     BIGINT[] NOT NULL DEFAULT '{}',
      keywords         TEXT[] NOT NULL DEFAULT '{}',
      certainty        TEXT    NOT NULL DEFAULT 'confirmed' CHECK (certainty IN ('uncertain','alleged','presumed','confirmed','contradicted')),
      source_chunk_ids BIGINT[] NOT NULL,
      pipeline_version TEXT    NOT NULL,
      run_id           UUID,
      created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS plot_thread_updates_latest_idx ON plot_thread_updates "
    "(novel_id, pipeline_version, thread_id, chapter DESC, id DESC);",
    "CREATE INDEX IF NOT EXISTS plot_thread_updates_chapter_idx ON plot_thread_updates "
    "(novel_id, pipeline_version, chapter);",
    "CREATE INDEX IF NOT EXISTS plot_thread_participants_gin ON plot_thread_updates USING gin (participants);",

    """
    CREATE TABLE IF NOT EXISTS extraction_contexts (
      novel_id         BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter          NUMERIC NOT NULL,
      pipeline_version TEXT    NOT NULL,
      source_sha256    TEXT    NOT NULL,
      context_sha256   TEXT    NOT NULL,
      prompt_sha256    TEXT,
      token_count      INT     NOT NULL DEFAULT 0,
      manifest         JSONB   NOT NULL,
      run_id           UUID,
      created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (novel_id, chapter, pipeline_version),
      CHECK (length(source_sha256)=64 AND length(context_sha256)=64)
    );
    """,
    "CREATE INDEX IF NOT EXISTS extraction_contexts_hash_idx ON extraction_contexts "
    "(novel_id, pipeline_version, context_sha256);",

    # 9. Extraction state
    """
    CREATE TABLE IF NOT EXISTS extraction_state (
      novel_id        BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter         NUMERIC NOT NULL,
      running_summary TEXT,                         -- Compatibility mirror of chapter summary
      run_id          UUID,
      model_label     TEXT,
      source_sha256   TEXT,
      processed_at    TIMESTAMPTZ DEFAULT now(),
      PRIMARY KEY (novel_id, chapter)
    );
    """,
    "ALTER TABLE extraction_state ADD COLUMN IF NOT EXISTS run_id UUID;",
    "ALTER TABLE extraction_state ADD COLUMN IF NOT EXISTS model_label TEXT;",
    "ALTER TABLE extraction_state ADD COLUMN IF NOT EXISTS source_sha256 TEXT;",
    "ALTER TABLE extraction_state ADD COLUMN IF NOT EXISTS pipeline_version TEXT;",
    "ALTER TABLE extraction_state ADD COLUMN IF NOT EXISTS context_sha256 TEXT;",

    # 10. Wiki cache
    """
    CREATE TABLE IF NOT EXISTS wiki_cache (
      novel_id        BIGINT NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      entity_id       BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
      chapter_ceiling NUMERIC NOT NULL,
      rendered_md     TEXT   NOT NULL,
      model           TEXT,
      evidence_ids    JSONB,                        -- fact/rel/state/thread/chunk provenance ids
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
    # Multi-worker claim lease: the worker that atomically claims a job stamps its opaque token
    # + a heartbeat time; a lease left unrenewed past the timeout is reclaimed (see importer/jobs.py).
    "ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS claim_token TEXT;",
    "ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;",
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

    # ── 20. Tag suggestions ────────────────────────────────────────────────
    # Status tags are owner/admin-controlled novel metadata. A reader of a shared
    # (public/global) novel can propose a tag set; the owner/admin accepts (applies it
    # to the novel) or rejects it. `tags` is the full proposed status_tags array.
    """
    CREATE TABLE IF NOT EXISTS tag_suggestions (
      id           BIGSERIAL PRIMARY KEY,
      novel_id     BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      from_user_id BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      tags         TEXT[]  NOT NULL DEFAULT '{}',
      note         TEXT,
      status       TEXT    DEFAULT 'pending',                 -- pending|accepted|rejected
      reviewed_by  BIGINT  REFERENCES users(id) ON DELETE SET NULL,
      created_at   TIMESTAMPTZ DEFAULT now(),
      reviewed_at  TIMESTAMPTZ
    );
    """,
    "CREATE INDEX IF NOT EXISTS tag_suggestions_novel_status_idx ON tag_suggestions (novel_id, status);",

    # ── 21. TTS jobs (audiobook narration) ─────────────────────────────────
    # Durable, resumable narration jobs, mirroring import_jobs. A single DB-polled worker
    # advances these one chapter at a time on the GPU sidecar and survives restarts. `scope`
    # is 'chapter' (one chapter) or 'book' (a bounded, cancellable batch). `options` carries
    # the explicit chapter list for a book job; `progress` carries {done,total,current_chapter,
    # stopped_reason?}. Status: queued → generating → done (+ failed, canceled).
    """
    CREATE TABLE IF NOT EXISTS tts_jobs (
      id          BIGSERIAL PRIMARY KEY,
      novel_id    BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      user_id     BIGINT  REFERENCES users(id) ON DELETE CASCADE,    -- who requested it (quota owner)
      scope       TEXT    NOT NULL DEFAULT 'chapter',                -- chapter|book
      voice_id    TEXT    NOT NULL,
      status      TEXT    NOT NULL DEFAULT 'queued',                 -- queued|generating|done|failed|canceled
      stage       TEXT,                                              -- human-readable current step
      progress    JSONB   DEFAULT '{}',                              -- {done,total,current_chapter,stopped_reason?}
      options     JSONB   DEFAULT '{}',                              -- {chapters:[..], language?}
      error       TEXT,
      created_at  TIMESTAMPTZ DEFAULT now(),
      updated_at  TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS tts_jobs_status_idx ON tts_jobs (status);",
    "CREATE INDEX IF NOT EXISTS tts_jobs_user_idx ON tts_jobs (user_id);",
    "CREATE INDEX IF NOT EXISTS tts_jobs_novel_idx ON tts_jobs (novel_id);",
    "CREATE INDEX IF NOT EXISTS tts_jobs_active_dedupe_idx ON tts_jobs "
    "((options->>'dedupe_key')) WHERE options ? 'dedupe_key' AND status IN ('queued','generating');",

    # ── 22. Chapter audio (narration cache / manifest) ─────────────────────
    # One row per generated narration. Shared base audio has user_id IS NULL and is reused by
    # every reader of the novel; a per-user overlay (edited translation) gets user_id set.
    # `content_version` is the chapters.content_version it was rendered from, so a base-content
    # change naturally invalidates the cache (a new version regenerates). Bytes live on disk
    # under ASSET_DIR; this row is the pointer.
    """
    CREATE TABLE IF NOT EXISTS chapter_audio (
      id               BIGSERIAL PRIMARY KEY,
      novel_id         BIGINT  NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
      chapter          NUMERIC NOT NULL,
      user_id          BIGINT  REFERENCES users(id) ON DELETE CASCADE,   -- NULL = shared base
      voice_id         TEXT    NOT NULL,
      language         TEXT,
      content_version  INT     NOT NULL DEFAULT 1,
      audio_path       TEXT    NOT NULL,                                 -- relative under ASSET_DIR
      duration_seconds INT,
      file_bytes       INT,
      created_at       TIMESTAMPTZ DEFAULT now(),
      FOREIGN KEY (novel_id, chapter) REFERENCES chapters(novel_id, number) ON DELETE CASCADE
    );
    """,
    # Two partial unique indexes because user_id is nullable: at most one shared row and one
    # per-user row per (novel, chapter, voice, version). Expression indexes treat NULL distinctly.
    "CREATE UNIQUE INDEX IF NOT EXISTS chapter_audio_base_uq ON chapter_audio "
    "(novel_id, chapter, voice_id, content_version) WHERE user_id IS NULL;",
    "CREATE UNIQUE INDEX IF NOT EXISTS chapter_audio_user_uq ON chapter_audio "
    "(novel_id, chapter, voice_id, content_version, user_id) WHERE user_id IS NOT NULL;",
    "CREATE INDEX IF NOT EXISTS chapter_audio_lookup_idx ON chapter_audio (novel_id, chapter, voice_id);",

    # ── 23. Generic durable jobs (scrape / codex build / translation) ──────
    # Unifies the fire-and-forget background work that used to run in FastAPI BackgroundTasks
    # (and would be lost on a deploy/restart after quota was already reserved). One row per
    # scheduled unit of work; a single DB-polled worker (novelwiki/jobs/worker.py) claims,
    # heartbeats, retries, and finalizes them, mirroring import_jobs/tts_jobs. `idempotency_key`
    # dedupes repeated clicks onto one active job; `quota_reserved`/`quota_consumed`/`quota_finalized`
    # make refund-on-failure explicit. Status: queued → running → done (+ failed, canceled).
    """
    CREATE TABLE IF NOT EXISTS jobs (
      id               BIGSERIAL PRIMARY KEY,
      kind             TEXT NOT NULL,                                    -- scrape|codex_build|translate|agy_smoke
      novel_id         BIGINT REFERENCES novels(id) ON DELETE CASCADE,
      user_id          BIGINT REFERENCES users(id) ON DELETE SET NULL,  -- requester (quota owner)
      status           TEXT NOT NULL DEFAULT 'queued',                  -- queued|running|done|failed|canceled
      stage            TEXT,                                            -- human-readable current step
      progress         JSONB DEFAULT '{}',                              -- {done,total,...}
      options          JSONB DEFAULT '{}',                              -- kind-specific args
      idempotency_key  TEXT,                                            -- dedupe repeated requests onto one active job
      quota_kind       TEXT,                                            -- quota bucket reserved up front (if any)
      quota_reserved   INT DEFAULT 0,
      quota_consumed   INT DEFAULT 0,                                   -- how much of the reservation was actually used
      quota_finalized  BOOLEAN DEFAULT FALSE,                           -- guards double refund
      error            TEXT,
      attempts         INT DEFAULT 0,
      max_attempts     INT DEFAULT 3,
      claim_token      TEXT,                                            -- opaque lease owner (see jobs/worker.py)
      claimed_at       TIMESTAMPTZ,
      backend_requested TEXT NOT NULL DEFAULT 'auto'
                       CHECK (backend_requested IN ('auto','api','agy')),
      execution_backend TEXT NOT NULL DEFAULT 'api'
                       CHECK (execution_backend IN ('api','agy')),
      backend_policy_version BIGINT,
      backend_fallback_allowed BOOLEAN NOT NULL DEFAULT FALSE,
      backend_fallback_from TEXT,
      backend_model    TEXT,
      not_before       TIMESTAMPTZ,
      cancel_requested_at TIMESTAMPTZ,
      created_at       TIMESTAMPTZ DEFAULT now(),
      updated_at       TIMESTAMPTZ DEFAULT now()
    );
    """,
    # Existing-install backfills (CREATE TABLE IF NOT EXISTS does not add columns).
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS backend_requested TEXT NOT NULL DEFAULT 'auto';",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS execution_backend TEXT NOT NULL DEFAULT 'api';",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS backend_policy_version BIGINT;",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS backend_fallback_allowed BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS backend_fallback_from TEXT;",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS backend_model TEXT;",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS not_before TIMESTAMPTZ;",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ;",
    """
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='jobs_backend_requested_check') THEN
        ALTER TABLE jobs ADD CONSTRAINT jobs_backend_requested_check
        CHECK (backend_requested IN ('auto','api','agy'));
      END IF;
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='jobs_execution_backend_check') THEN
        ALTER TABLE jobs ADD CONSTRAINT jobs_execution_backend_check
        CHECK (execution_backend IN ('api','agy'));
      END IF;
    END $$;
    """,
    "CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);",
    "CREATE INDEX IF NOT EXISTS jobs_kind_idx ON jobs (kind);",
    "CREATE INDEX IF NOT EXISTS jobs_novel_idx ON jobs (novel_id);",
    "CREATE INDEX IF NOT EXISTS jobs_user_idx ON jobs (user_id);",
    "CREATE INDEX IF NOT EXISTS jobs_created_idx ON jobs (created_at DESC);",
    "CREATE INDEX IF NOT EXISTS jobs_backend_queue_idx "
    "ON jobs (execution_backend, status, not_before, updated_at);",
    # Recreate rather than IF-NOT-EXISTS: the old predicate omitted waiting_provider,
    # which would silently let duplicate work through while subscription capacity waits.
    "DROP INDEX IF EXISTS jobs_active_idem_idx;",
    "CREATE INDEX jobs_active_idem_idx ON jobs ((idempotency_key)) "
    "WHERE idempotency_key IS NOT NULL AND status IN ('queued','running','waiting_provider');",

    # One row per provider invocation. A job may have several attempts/chapters and
    # disambiguation may be a child run of a codex extraction run.
    """
    CREATE TABLE IF NOT EXISTS ai_execution_runs (
      id                 UUID PRIMARY KEY,
      job_id             BIGINT REFERENCES jobs(id) ON DELETE CASCADE,
      import_job_id      BIGINT REFERENCES import_jobs(id) ON DELETE CASCADE,
      parent_run_id      UUID REFERENCES ai_execution_runs(id) ON DELETE SET NULL,
      user_id            BIGINT REFERENCES users(id) ON DELETE SET NULL,
      novel_id           BIGINT REFERENCES novels(id) ON DELETE SET NULL,
      workload           TEXT NOT NULL,
      backend            TEXT NOT NULL CHECK (backend IN ('api','agy')),
      model              TEXT,
      runner_version     TEXT,
      plugin_version     TEXT,
      plugin_sha256      TEXT,
      status             TEXT NOT NULL,
      attempt            INT NOT NULL DEFAULT 1,
      input_sha256       TEXT,
      output_sha256      TEXT,
      workspace_relpath  TEXT,
      process_group_id   INT,
      process_started_at TEXT,
      exit_code          INT,
      failure_code       TEXT,
      error_summary      TEXT,
      metrics            JSONB NOT NULL DEFAULT '{}',
      started_at         TIMESTAMPTZ,
      finished_at        TIMESTAMPTZ,
      created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
      CHECK ((job_id IS NOT NULL)::INT + (import_job_id IS NOT NULL)::INT = 1)
    );
    """,
    "CREATE INDEX IF NOT EXISTS ai_runs_job_idx ON ai_execution_runs (job_id, created_at);",
    "CREATE INDEX IF NOT EXISTS ai_runs_status_idx ON ai_execution_runs (backend, status, created_at);",

    # Small non-secret health record written by the dedicated host worker.
    """
    CREATE TABLE IF NOT EXISTS ai_worker_heartbeats (
      worker_id       TEXT PRIMARY KEY,
      backend         TEXT NOT NULL,
      status          TEXT NOT NULL,
      version         TEXT,
      plugin_version  TEXT,
      plugin_sha256   TEXT,
      details         JSONB NOT NULL DEFAULT '{}',
      heartbeat_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      started_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS ai_worker_heartbeats_backend_idx "
    "ON ai_worker_heartbeats (backend, heartbeat_at DESC);",

    # ── 24. Audit events ───────────────────────────────────────────────────
    # Durable, append-only operational log: job lifecycle, quota reservations/refunds, and (room
    # for) auth/visibility/admin actions. `request_id` ties an event back to the HTTP request that
    # triggered it (see the X-Request-ID middleware in novelwiki/api/app.py).
    """
    CREATE TABLE IF NOT EXISTS audit_events (
      id          BIGSERIAL PRIMARY KEY,
      event       TEXT NOT NULL,                                        -- job.created|job.done|quota.refund|...
      user_id     BIGINT REFERENCES users(id) ON DELETE SET NULL,
      novel_id    BIGINT REFERENCES novels(id) ON DELETE SET NULL,
      request_id  TEXT,
      data        JSONB DEFAULT '{}',
      created_at  TIMESTAMPTZ DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS audit_events_event_idx ON audit_events (event, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS audit_events_user_idx ON audit_events (user_id, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS audit_events_novel_idx ON audit_events (novel_id, created_at DESC);",
]

# Tables in dependency order (children first) — used by reset_db to drop cleanly.
ALL_TABLES = [
    "audit_events",
    "ai_worker_heartbeats",
    "ai_execution_runs",
    "jobs",
    "tag_suggestions",
    "contributions",
    "chapter_overlays",
    "chapter_audio",
    "tts_jobs",
    "import_jobs",
    "provider_budget",
    "assets",
    "translation_glossary",
    "bookmarks",
    "reading_progress",
    "query_cache",
    "wiki_cache",
    "extraction_contexts",
    "plot_thread_updates",
    "plot_threads",
    "relationship_state_transitions",
    "entity_state_transitions",
    "entity_activity",
    "memory_segments",
    "chapter_summaries",
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
    "ai_request_locks",
    "email_tokens",
    "sessions",
    "oauth_accounts",
    "user_ai_backend_policies",
    "users",
    "app_migrations",
]


async def init_database():
    db_name = _database_name(settings.DATABASE_URL)

    # 1. Connect to superuser DB to ensure the configured database exists.
    try:
        conn = await asyncpg.connect(settings.DB_SUPERUSER_URL)
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = $1);",
            db_name,
        )
        if not exists:
            logger.info("Database %r does not exist. Creating...", db_name)
            await conn.execute(f"CREATE DATABASE {_quote_ident(db_name)};")
            logger.info("Database %r created successfully.", db_name)
        await conn.close()
    except Exception as e:
        logger.warning(f"Could not check/create database using superuser URL: {e}")

    # 2. Connect to the configured database and apply schema.
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL)
        logger.info("Applying migrations and DDL queries to %r...", db_name)

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
