# Reading module (`novelwiki/modules/reading/`)

**Responsibility:** the chapter store and the act of reading it: the table of contents,
chapter content resolution (base text vs. a reader's personal overlay), reading progress
and the **trusted spoiler ceiling**, bookmarks, per-user translation overlays, and the
contribute-back review flow. Reading owns the text that every other pipeline consumes —
translation, codex extraction, narration, and import all reach chapters *through Reading
capabilities*, never by touching `chapters` directly.

**Owned tables:** `chapters`, `reading_progress`, `bookmarks`, `chapter_overlays`,
`contributions`.

---

## Public contract (`public.py`) — the largest in the codebase

Nine protocol declarations, grouped by seven consumer relationships:

| Protocol | Consumer | Purpose |
|---|---|---|
| `ReadingApi` | HTTP layer | progress + bookmarks basics |
| `ReadingTransactionApi` | workflows (`update_source_offset`) + route façade | chapter listing/snapshots, renumbering, base-content updates, overlays, contributions |
| `ReadingTranslationTransactionApi` | `commit_translation` workflow | the atomic, optimistic-concurrency chapter-translation commit |
| `ReadingTranslationApi` | Translation module/worker | staging batches (AGY), candidates, pending ranges, started/failed marks, source lengths |
| `ReadingIngestionApi` / `ReadingIngestionTransactionApi` | Acquisition (scraper + `commit_import` workflow) | `resume_url`, `upsert_ingested_chapter` (the single funnel through which ALL new text enters), source versions, overlay-conflict marking, content-version preservation |
| `ReadingNarrationApi` | Narration | `resolve_narration_text` (overlay-aware), `prose_chapters` |
| `ReadingCodexApi` / `ReadingCodexTransactionApi` | Codex | chapter snapshots/numbers, `chapter_at_or_before(ceiling)`, and `locked_chapter_snapshot` (row-locked read inside the extraction-commit transaction) |

DTOs in `application/dto.py`: `Progress`, `Bookmark`, `ChapterListItem`,
`ChapterSnapshot`, `Contribution`.

## Core concepts

### Global chapter numbering

`chapters` is keyed `(novel_id, number NUMERIC)` — floats like `15.5` are legal. `number`
is the **global** reading index: each source's local numbering is mapped on via
`sources.chapter_offset`, so a novel stitched from several sites reads as one sequence.
Changing an offset renumbers through the `update_source_offset` workflow (all-or-nothing,
refused while codex artifacts exist on the old numbering).

### The trusted ceiling

`reading_progress` (PK `(user_id, novel_id)`) tracks `last_chapter` + `scroll_pct`
(resume position — client-driven, low trust) and `max_chapter_read` (**monotonic**,
advanced when an authenticated chapter snapshot is served — the spoiler ceiling).
`PUT /progress` never writes `max_chapter_read`.
`PostgresReadingRepository.trusted_ceiling()` is
what Codex's `CeilingPort` resolves through: a reader's requested ceiling is clamped to
what the server has seen them read. Full model:
[../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

### Content resolution & versioning

A chapter's readable text is `chapters.content` (English text, or the translation for raw
sources), with `original_text` preserving the source language so re-translation never
needs a re-scrape, and `raw_html`/rich content for imported books (asset URLs rewritten to
the access-controlled endpoint by the HTTP adapter). Every base-content change bumps
`content_version`. A reader with a personal **overlay** for `(user, novel, chapter)` sees
the overlay instead; the overlay records the `base_version` it forked from, so a later
base change marks it `conflict` and the UI offers a base-vs-mine resolver. Narration's
audio cache is keyed by `content_version` too — text edits naturally invalidate audio.

### Overlays & contributions (translation collaboration)

- `PUT /api/novels/{id}/chapter/{n}/overlay` — save a personal override (origin
  `manual_edit` or `self_translated`).
- `POST …/self-translate` — machine-translate a raw chapter *into the caller's overlay*
  (metered against **their** quota; the shared base is untouched).
- `POST …/contribute` — offer the overlay to the owner; `contribution_policy='auto'`
  merges immediately when the base hasn't moved, else it lands in the owner's inbox
  (`GET /api/novels/{id}/contributions`, `accept`/`reject`). Accepting merges into the
  base via `update_base_content` (which bumps the version, marks other users' overlays
  conflicted, but can keep the accepted contributor's overlay coherent via
  `keep_overlay_user`).
- `POST …/resolve` — the conflicted reader keeps base (drop overlay), keeps theirs
  (re-anchor to current version), or edits.

## HTTP surface (auth required, `/api`)

TOC & content: `GET /novels/{id}/chapters`, `GET /novels/{id}/chapter/{n}` (returns
content + prev/next; opening a *raw pending* chapter triggers on-demand translation and
schedules prefetch of the next `TRANSLATE_PREFETCH` chapters as background work);
`PUT …/chapter/{n}/content` (owner/admin base edit). Progress: `GET/PUT
/novels/{id}/progress`. Bookmarks: `GET/POST /novels/{id}/bookmarks`,
`DELETE …/bookmarks/{bid}`. Plus the overlay/contribution routes above.

## Application & outbound

- `application/services.py::ReadingService` — resume-progress/bookmark use cases guarded
  by Catalog access; progress PUT chapter-exists validation. The chapter snapshot query
  in the outbound repository performs the monotonic `max_chapter_read` advance.
- `application/migration.py` — the route-facing façade for chapter/overlay/contribution
  flows (composed by Bootstrap's `build_reading_migration_service`), including on-demand
  translation triggering through an injected Translation capability.
- `adapters/outbound/postgres.py::PostgresReadingRepository` — "the sole progress/bookmark
  SQL writer"; chapter span, trusted ceiling, TOC, snapshots, base-content update +
  overlay conflict marking, contribution lifecycle.
- `adapters/outbound/translation.py` — the Translation-facing queries (pending ranges,
  staging with `translation_run_id`/`translation_source_sha256`, candidates, failure
  resets) + the transaction-bound `commit_translation` implementation (row lock,
  hash/version compare, idempotency detection).
- `adapters/outbound/ingestion.py` — `upsert_ingested_chapter` (scraper + import funnel;
  respects `force`, preserves `content_version` minimums so an import replay can't
  regress overlay anchors, sets `kind`/`part_label` for non-chapter sections),
  source-chapter deletion, overlay-conflict marking, cross-source number sets.
- `adapters/outbound/codex.py`, `narration.py` — the gateways Codex/Narration consume.

## Collaboration notes

Reading exposes many capabilities but consumes few: Catalog (access checks) and — for
self-translate/on-demand translation — an injected Translation executor plus Identity
quota. Everything else consumes Reading. That asymmetry is why its `public.py` is the
biggest file of its kind.
