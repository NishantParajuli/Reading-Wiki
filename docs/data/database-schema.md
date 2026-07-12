# Database schema reference

> **Source of truth:** `novelwiki/db/schema.py` — a list of idempotent DDL statements
> applied on every startup (and via `python -m novelwiki.db.schema`). The normalized DDL
> is contract-frozen in `tests/contracts/snapshots/schema.json`. This page documents all
> **39 tables**, grouped by owning module, with the reasoning behind the non-obvious
> columns. Single-writer ownership is enforced by the architecture checker
> ([../architecture/enforcement.md](../architecture/enforcement.md)).

**Engine facts**

- PostgreSQL with two extensions: `vector` (pgvector — embedding columns + HNSW cosine
  indexes when `EMBED_DIM ≤ 2000`, otherwise sequential scan, which is fine at webnovel
  scale) and `pg_trgm` (trigram GIN indexes for fuzzy entity/alias matching).
- Schema management is **idempotent DDL, not migration files**: `CREATE TABLE IF NOT
  EXISTS` plus explicit `ALTER TABLE … ADD COLUMN IF NOT EXISTS` backfills so an existing
  live DB gains new columns without a reset. One data-rewriting legacy migration exists
  (`db/migrate_multiuser.py`, marker-guarded via `app_migrations`).
- Chapter numbers are `NUMERIC` everywhere (float chapters like `15.5` are legal), and
  **chapter is the spoiler key**: every codex-owned row carries one.
- `reset-db` drops `ALL_TABLES` in dependency order (note: `auth_rate_limits` is
  intentionally absent from that list — preserved behavior, ADR 002).

---

## Platform-owned

### `app_migrations`

Durable one-time migration markers. `name TEXT PK`, `applied_at`, `details JSONB`.
Prevents guarded data migrations from re-interpreting valid post-migration rows (e.g.
ownerless novels after a user delete) as legacy single-user data on a later restart.

### `audit_events`

Append-only operational log. `id`, `event` (`job.created`, `job.done`, `quota.refund`,
auth/admin actions…), `user_id` (SET NULL on user delete), `novel_id`, `request_id`
(ties the event to the HTTP request via the `X-Request-ID` middleware), `data JSONB`,
`created_at`. Indexed by event/user/novel + time.

## Identity-owned

### `users`

One row per human. `email` (unique, lowercased), `email_verified`, `password_hash`
(**NULL for OAuth-only accounts**), `username` (unique handle for `/u/<username>`),
`display_name`, `bio`, `avatar_path` (relative under `ASSET_DIR/_users/<id>/`),
`role` (`user`|`admin`), `status` (`active`|`suspended`|`banned` — suspend/ban without
deleting data), per-user quota overrides `quota_translated_chapters`, `quota_ocr_pages`,
`quota_codex_builds`, `quota_tts_chapters` (**NULL ⇒ fall back to `DEFAULT_QUOTA_*`
settings**), `prefs JSONB` (reader preferences synced across devices), timestamps.

### `oauth_accounts`

Provider links. `user_id`, `provider` (`google`|`discord`), `provider_account_id`,
`UNIQUE (provider, provider_account_id)`. A user may link several providers.

### `sessions`

Server-side sessions. **`token_hash` is the PK** — the cookie holds the opaque token, the
DB only its hash; deleting the row (logout/ban) revokes instantly. `user_id`,
`created_at`, `expires_at`, `last_seen_at`, `user_agent`.

### `email_tokens`

One-time verification/reset tokens, hashed at rest. `user_id`, `kind` (`verify`|`reset`),
`token_hash` (unique), `expires_at`, `used_at` (single-use guard).

### `auth_rate_limits`

Durable fixed-window abuse counters. `bucket_key` (**scoped hashes** of IP/account/email/
token — raw identifiers are never stored), `count`, `reset_at`.

### `quota_usage`

The monthly spend meter: PK `(user_id, period)` where `period` is the first-of-month
date; counters `translated_chapters`, `ocr_pages`, `codex_builds`, `tts_chapters`.
Refunds decrement with a floor of zero.

## AI-Execution-owned

### `user_ai_backend_policies`

Admin-owned AGY entitlement (no row = API-only). `user_id PK`, `agy_enabled`,
`default_backend` (`api`|`agy`, CHECK: must be `api` unless enabled), `agy_workloads
TEXT[]` (CHECK ⊆ {`translate_batch`, `codex_extract`, `segment_import`, `ocr_pages`,
`ask`, `profile_synthesis`}), `fallback_to_api`, `max_concurrent_agy_jobs` (1–4),
`policy_version` (bumped on every change; stale queued decisions are detected),
`notes`, `granted_by`.

### `ai_request_locks`

Self-expiring concurrency slots for **read-side** AI (denial-of-wallet control): one row
per in-flight uncached Ask/profile-synthesis; `user_id`, `kind`, `expires_at` (a crashed
request can't hold a slot forever).

### `provider_budget`

Daily provider call counter that survives restarts (Gemini free-tier guard). PK
`(provider, day)`, `used`.

### `ai_execution_runs`

One row per provider invocation (a job may have many: attempts, chapters, child runs).
`id UUID PK`, exactly one of `job_id` / `import_job_id` (CHECK), `parent_run_id`
(disambiguation/verification children), `user_id`, `novel_id`, `workload`, `backend`
(`api`|`agy`), `model`, `runner_version`, `plugin_version`, `plugin_sha256`, `status`,
`attempt`, `input_sha256`/`output_sha256` (artifact integrity), `workspace_relpath`,
`process_group_id` + `process_started_at` (identity-verified orphan reaping),
`exit_code`, `failure_code`, `error_summary`, `metrics JSONB`, timing columns.

### `ai_worker_heartbeats`

Small non-secret health record from the dedicated AGY host worker: `worker_id PK`,
`backend`, `status`, versions + plugin hash, `details JSONB`, `heartbeat_at`,
`started_at`. Drives the admin health panel (stale after
`AGY_WORKER_HEALTH_TTL_SECONDS`).

## Catalog-owned

### `novels`

The library aggregate. `title`, `author`, `cover_url`, `description`,
`original_language`, `codex_enabled` (opt-in pipeline), `shelf` + `status_tags`
(legacy/owner defaults — per-user values live in `library_entries`), `series` (multi-
volume import grouping: a later volume of a detected series appends instead of creating
a duplicate novel), `owner_id` (SET NULL on user delete — moderation is deliberate),
`visibility` (`private`|`public`|`global`), `contribution_policy` (`manual`|`auto` —
how contribute-back offers merge), timestamps. Indexed by shelf/series/owner/visibility.

### `library_entries`

Per-user library membership + curation: `UNIQUE (user_id, novel_id)`, `shelf`
(`to_read`|`reading`|`completed`), `status_tags TEXT[]`, `added_at`. Adding a shared
novel here is the "read the shared copy" action — one text, many readers.

### `tag_suggestions`

Reader-proposed status tags for shared novels: `novel_id`, `from_user_id`,
`tags TEXT[]` (the full proposed array), `note`, `status`
(`pending`|`accepted`|`rejected`), `reviewed_by`, `reviewed_at`.

## Acquisition-owned

### `sources`

A novel's ingestion sources. `novel_id`, `adapter` (registry key: `fenrirealm`,
`readhive`, `boti-translations`, `69shuba`, `wetriedtls`, or the import adapter),
`start_url` (or file path for imports), `config JSONB` (per-source knobs),
`language`, `is_raw` (needs translation), **`chapter_offset NUMERIC`** (source-local
number + offset = the novel's GLOBAL chapter number — the mechanism that stitches
multiple sites into one sequence), `label`, `last_scraped_at`.

### `import_jobs`

Durable, resumable EPUB/PDF ingestion state (big artifacts live on disk; this row is
status + the small editable plan). `novel_id` (null until target chosen), `source_id`,
`format` (`epub`|`pdf`), `original_path`, `file_sha256`, `status` (see
[../pipelines/file-import.md](../pipelines/file-import.md): `receiving`, `uploaded`,
`parsing`, `awaiting_review`, `ocr_pending`, `ocr_running`, `ocr_paused`, `committing`,
`commit_running`, `committed`, `failed`, `canceled`), `stage` (human-readable step),
`detected_meta JSONB`, **`plan JSONB`** (the editable segmentation plan the user reviews),
`stats`, `cost_estimate`, `progress` (`{done,total,unit}`), `options`
(`{gemini_first, target, is_raw, …}`), `error`, `user_id` (uploader), and the lease pair
`claim_token`/`claimed_at` (multi-worker safety).

### `assets`

Extracted images (covers, illustrations, page scans). Bytes live under
`ASSET_DIR/<novel_id>/`; the row is the pointer: `sha256` + `UNIQUE (novel_id, sha256)`
(content-addressed dedup — an image shared across chapters is stored once), `path`,
`mime`, `kind` (`cover`|`illustration`|`page_scan`), `width`/`height`.

## Reading-owned

### `chapters`

PK `(novel_id, number NUMERIC)` — `number` is the GLOBAL reading index and the value
compared against the spoiler ceiling everywhere. `source_id` (SET NULL), `title`, `url`,
`raw_html` (rich content for imports), `original_text` (cleaned source-language text —
re-translation never needs a re-scrape), **`content`** (what the reader sees: English
text or the translation), `language`, `is_translated`, `translation_status`
(`none`|`pending`|`done`|`failed`), `translation_model`, `word_count`,
**`content_version`** (bumped on every base-content change; the anchor for overlay
conflict detection and audio-cache invalidation), `kind`
(`chapter`|`frontmatter`|`interlude`|`backmatter` — import sections the reader can
skip), `part_label` ("Volume 1" TOC grouping), `translation_run_id UUID` +
`translation_source_sha256` (AGY staging identity: a crashed/retried batch can't commit
a chapter staged by another run), `scraped_at`.

### `reading_progress`

PK `(user_id, novel_id)`. `last_chapter` + `scroll_pct` (resume position; client-driven),
**`max_chapter_read`** (monotonic, server-observed — THE spoiler ceiling), `updated_at`.

### `bookmarks`

`user_id`, `novel_id`, `chapter`, `note`, indexed `(user_id, novel_id, chapter)`.

### `chapter_overlays`

Per-user translation override on top of shared base content. `UNIQUE (user_id, novel_id,
chapter)`; `content`, **`base_version`** (the `chapters.content_version` it forked from),
`origin` (`manual_edit`|`self_translated`), **`conflict`** (set when the base moved under
the overlay; drives the base-vs-mine resolver).

### `contributions`

Contribute-back "pull requests" of overlays to the novel owner. `novel_id`,
`from_user_id`, `kind` (`translation`), `chapter`, `content`, `base_version`, `status`
(`pending`|`accepted`|`rejected`|`auto_merged`), `reviewed_by`, `reviewed_at`.

## Translation-owned

### `translation_glossary`

Per-novel name/term consistency anchor. `UNIQUE (novel_id, source_term)`;
`source_term` (e.g. 林轩), `translation` (canonical rendering, e.g. Lin Xuan),
`term_type` (`name`|`place`|`skill`|`item`|`term`), `notes`, **`locked`** (user-pinned
renderings the auto-glossary never overwrites).

## Codex-owned (11 tables — every row chapter-keyed for spoiler safety)

### `chunks`

Retrieval passages. `UNIQUE (novel_id, chapter, chunk_index)`; `text`, `token_count`,
`embedding vector(EMBED_DIM)`; composite FK to `chapters(novel_id, number)` ON DELETE
CASCADE (deleting a chapter removes its chunks). HNSW cosine index when dim ≤ 2000.

### `entities`

Canonical entities. `canonical_name`, `type` (`character`|`location`|`faction`|`item`|
`concept`|`organization`), `description`, `name_embedding` (embeds "name + description"
for semantic linking), **`first_seen_chapter`** (an entity is invisible until its first
appearance is within the ceiling). Trigram GIN index on name.

### `entity_descriptions`

Per-chapter description history — `UNIQUE (entity_id, chapter)` — so a profile shows the
description *as of the reader's ceiling*, not the latest.

### `entity_aliases`

Alternate names with **`revealed_at_chapter`** — an alias only resolves once its reveal
chapter is within the ceiling. Trigram-indexed.

### `identity_links`

"A is B" reveals (`entity_a`, `entity_b`, **`revealed_at_chapter`**, `note`) — powers
identity-reveal banners and persona folding, only past the reveal chapter.

### `entity_facts`

The atomic knowledge unit: `entity_id`, **`chapter` (the spoiler key)**, `fact_type`
(`trait`|`status`|`backstory`|`action`|`location`|`possession`|`belief`|…), `content`
(natural-language fact as known at that chapter), `data JSONB`,
`source_chunk_ids BIGINT[]` (provenance for citations).

### `relationships`

`source_id` → `target_id`, `chapter`, `relation_type` (`mentor`|`ally`|`enemy`|`family`|
`romantic`|`rival`|`subordinate`|…), `directed`, `content`, `data`, `source_chunk_ids`.

### `events`

`chapter`, `description`, `participants BIGINT[]` (entity ids), `location_id`,
`significance`, `data`, `source_chunk_ids`.

### `extraction_state`

Per-chapter pipeline state: PK `(novel_id, chapter)`; **`running_summary`** (the
story-so-far text that feeds the next chapter's extraction), `run_id UUID`,
`model_label`, **`source_sha256`** (hash of the exact text extracted — the
`commit_codex_extraction` workflow verifies it under lock), `processed_at`.

### `wiki_cache`

Synthesized entity profiles, cached per ceiling: PK `(novel_id, entity_id,
chapter_ceiling)`; `rendered_md`, `model`, `evidence_ids JSONB`.

### `query_cache`

Ask answers, cached per ceiling: `UNIQUE (novel_id, query_hash, chapter_ceiling)` where
`query_hash` = md5 of the normalized question; `answer_md`, `evidence_ids`.

## Narration-owned

### `tts_jobs`

Durable narration jobs. `novel_id`, `user_id` (quota owner), `scope`
(`chapter`|`book`), `voice_id`, `status` (`queued`|`generating`|`done`|`failed`|
`canceled`), `stage`, `progress` (`{done,total,current_chapter,stopped_reason?}`),
`options` (`{chapters:[…], language?, dedupe_key…}`), `error`. A partial unique-ish
dedupe index on `options->>'dedupe_key'` over active statuses prevents duplicate
in-flight chapter jobs.

### `chapter_audio`

The narration cache/manifest. `novel_id`, `chapter` (composite FK to chapters),
`user_id` (**NULL = shared base audio reused by every reader; set = overlay audio for
one user**), `voice_id`, `language`, **`content_version`** (rendered-from version —
base edits invalidate naturally), `audio_path` (relative under `AUDIO_DIR`),
`duration_seconds`, `file_bytes`. Two partial unique indexes (base row vs per-user row
per (novel, chapter, voice, version)) because `user_id` is nullable.

## Work-owned

### `jobs`

The generic durable-job queue (scrape / codex_build / translate / agy_smoke). Fields in
four groups:
- *Lifecycle*: `kind`, `novel_id`, `user_id` (requester/quota owner; SET NULL on user
  delete), `status` (`queued`|`running`|`waiting_provider`|`done`|`failed`|`canceled`),
  `stage`, `progress JSONB`, `options JSONB`, `error`, `attempts`/`max_attempts`,
  `created_at`/`updated_at`.
- *Dedupe*: `idempotency_key` + partial index over **active** statuses (including
  `waiting_provider` — capacity-parked work still dedupes).
- *Quota*: `quota_kind`, `quota_reserved`, `quota_consumed`, **`quota_finalized`**
  (exactly-once settlement guard).
- *Execution backend*: `backend_requested` (`auto`|`api`|`agy`), `execution_backend`
  (`api`|`agy` — which worker family may claim it), `backend_policy_version`,
  `backend_fallback_allowed`/`backend_fallback_from`, `backend_model`, `not_before`
  (provider-wait release time), `cancel_requested_at`, and the lease pair
  `claim_token`/`claimed_at`.

---

## Entity-relationship sketch (the load-bearing edges)

```
users ─┬─< sessions / oauth_accounts / email_tokens / quota_usage / ai_request_locks
       ├─< library_entries >─ novels ─┬─< sources ─< chapters (novel_id,number)
       ├─< reading_progress ──────────┤              │  ▲ composite FK
       ├─< chapter_overlays ──────────┤              ├─< chunks ─ embedding
       ├─< contributions ─────────────┤              └─< chapter_audio
       ├─< import_jobs / tts_jobs / jobs (requester)
       └── user_ai_backend_policies   ├─< entities ─< entity_{descriptions,aliases,facts}
                                      │              ├─< relationships / identity_links
                                      │              └─< wiki_cache
                                      ├─< events / extraction_state / query_cache
                                      └─< assets / tag_suggestions
jobs ─< ai_execution_runs >─ import_jobs        audit_events (user_id, novel_id, request_id)
```

Deletion semantics: novel delete cascades everything novel-scoped; user delete cascades
personal data but **sets NULL** on `novels.owner_id`, `jobs.user_id`,
`audit_events.user_id` (owned novels and operational history survive).
