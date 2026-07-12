# Catalog module (`novelwiki/modules/catalog/`)

**Responsibility:** the *novel* as a library object — its metadata, who owns it, who can
see it (`private`/`public`/`global`), each user's personal library membership and shelf,
and reader-proposed tag suggestions. Catalog is the system's **access-control authority**
for novels: every other module asks Catalog "may this principal read/edit novel X?"
before doing anything.

**Owned tables:** `novels`, `library_entries`, `tag_suggestions`.

---

## Public contract (`public.py`)

- **`NovelAccess`** — frozen access snapshot: `novel_id`, `owner_id`, `visibility`,
  `contribution_policy`, `title`, `description`.
- **`CatalogAccess`** — the two questions everyone asks:
  - `require_readable(novel_id, principal)` → `NovelAccess` or `NotFound`/`Forbidden`.
    Readable = owner, or visibility `public`/`global`, or admin.
  - `require_editable(novel_id, principal)` — owner or admin.
- **`NovelDraft` / `ImportedNovelDraft`** — creation payloads (title, author, description,
  cover, `original_language`, `codex_enabled`; imports add `series`, `owner_id`,
  `visibility`).
- **`CatalogTransactionApi`** — the workflow-bound capability: `create_novel`,
  `add_to_library`, `delete_novel`, `enable_codex`, `create_imported_novel`,
  `novel_exists`, `codex_enabled`, `set_cover_if_missing`, `touch_novel`, and the tag
  suggestion lifecycle (`create/list/accept/reject_tag_suggestion`). Participates in the
  `create_novel_with_source`, `delete_novel`, and `commit_import` workflows.

## Domain rules (`domain/policies.py`, `domain/tags.py`)

- Visibility: `private` (owner+admin only) → `public` (any signed-in reader may read/add)
  → `global` (admin-curated shared library). **Only an admin may set or clear `global`.**
- Ownership: `owner_id` is the uploader; `NULL` = system/global stock. Deleting a user
  keeps their novels (owner becomes NULL) — moderation is deliberate, not cascade.
- Per-user vs. novel-level fields: `shelf` and `status_tags` on `novels` are
  legacy/owner defaults; the *real* per-reader shelf/tags live in `library_entries`
  (one row per (user, novel), UNIQUE). "One shared text, many readers" falls out of this.
- Tag normalization/validation in `domain/tags.py`; suggestions carry the *full proposed
  array*, and accepting replaces the novel's `status_tags`.

## Application

- `access.py::CatalogAccessService` — readable/editable checks + library add/remove +
  visibility transitions + metadata updates (with the rule that any *reader* may set
  their own shelf, but only owner/admin may edit novel metadata).
- `migration.py::CatalogMigrationService` — the route-facing façade for compound
  operations: create-novel(+first source) via the workflow, cover upload
  (`store_cover` → Acquisition asset storage through an injected port),
  delete-novel via the workflow + injected cleanup, and the tag-suggestion flows.
  Constructor takes `(uow_factory, validate_source_url, cleanup)` — URL validation is
  Acquisition's scraper-safety check, injected so Catalog never imports the scraper.
- `transactions.py::CatalogTransactionService` — the connection-bound implementation of
  `CatalogTransactionApi`.

## HTTP surface (`adapters/inbound/http.py`, mounted under `/api`, auth required)

| Route | Behavior |
|---|---|
| `POST /api/novels` | create (owned by caller, `private` by default), optional first source; runs the `create_novel_with_source` workflow |
| `POST /api/novels/{id}/cover` | upload cover (size-limited read), stored via Acquisition, URL returned is the access-controlled asset route |
| `DELETE /api/novels/{id}` | `delete_novel` workflow + post-commit file cleanup |
| `PATCH /api/novels/{id}` | metadata edit (owner/admin) / per-user shelf (any reader) |
| `PATCH /api/novels/{id}/visibility` | visibility transition (global admin-only) |
| `POST /api/novels/{id}/library` / `DELETE …/library` | add/remove from caller's library (progress/bookmarks kept on remove) |
| `POST /api/novels/{id}/tag-suggestions` | reader proposes a tag set for a shared novel |
| `GET /api/novels/{id}/tag-suggestions` | owner/admin inbox (default `pending`) |
| `POST …/tag-suggestions/{sid}/accept` / `reject` | apply or decline |

Reads like the library grid, novel detail, and Discover are **not** here — they are
Experience projections (`GET /api/novels`, `GET /api/novels/{id}`, `GET /api/discover`)
that join across owners read-only. Catalog answers *permission*; Experience answers
*presentation*.

## Outbound

`adapters/outbound/postgres.py::PostgresCatalogRepository` — sole SQL writer for the three
owned tables; also `novel_titles(ids)` used by projections through injected ports.

## Collaboration notes

- `CatalogAccessService` instances are injected into Reading, Codex, Narration,
  Translation, Acquisition, and Experience (each behind that consumer's own port name:
  `NarrationAccessPort`, `CatalogEditPort`, `CatalogAccessPort`, …).
- `touch_novel` bumps `updated_at` when chapters land (scrape/import), which feeds
  Discover's freshness filter.
- `enable_codex` is flipped before the first codex job is inserted. This is the optional
  owner command inside ADR 003's guarded-compensation sequence, not part of one DB
  transaction with scheduling; a scheduling exception refunds quota but may leave the
  harmless opt-in flag enabled.
