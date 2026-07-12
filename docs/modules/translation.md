# Translation module (`novelwiki/modules/translation/`)

**Responsibility:** turning raw (foreign-language) chapter text into English —
on-demand when a reader opens a chapter, prefetched in the background, or as durable
batch jobs — while keeping names/terms consistent through a per-novel **glossary**.
The pipeline walkthrough is [../pipelines/translation.md](../pipelines/translation.md).

**Owned table:** `translation_glossary` (chapter text itself belongs to Reading;
Translation writes it only through Reading's transaction capability inside the
`commit_translation` workflow).

---

## Public contract (`public.py`)

- **`GlossaryTerm`** — `(id, source_term, translation, term_type, notes, locked)`.
- **`TranslationTransactionApi`** — glossary CRUD + `seed_established_terms` (from codex
  entities) + `insert_discovered_terms` (new terms found during a translation commit —
  bound inside the `commit_translation` workflow so terms land atomically with the
  chapter).
- **`TranslationApi`** — `translate_chapter(novel_id, chapter, user_id)` and
  `translate_raw_text(text)` — the executable capability injected into Reading (on-demand
  open + self-translate).

## How a translation happens (`adapters/outbound/runtime.py`)

The engine, shared by every trigger (reader open, prefetch, batch job, CLI):

1. **Per-chapter lock** (`_lock_for(novel_id, number)`) — no duplicate concurrent work.
2. **Glossary load & split** — `locked`/confirmed mappings ("translate 林轩 as Lin Xuan")
   vs. established spellings (soft guidance).
3. **Prompted call** — `domain/prompts.py` templates + `MODEL_TRANSLATE` via OpenRouter;
   input capped at `TRANSLATE_MAX_INPUT_CHARS` (48k chars).
4. **Delimiter-framed parse** — `(translated_title, translation_text, new_terms)`.
5. **Atomic commit** — the `commit_translation` workflow: Reading's row-locked,
   optimistic commit (`expected_source_hash` = SHA-256 of the `original_text` actually
   translated; `expected_content_version`), then discovered-term upsert (never
   overwriting existing rows — user-pinned `locked` terms always win), then Work
   metering (`quota_consumed += 1`) when a job drove it. Idempotent replays skip terms
   and metering.
6. **Status bookkeeping** — `chapters.translation_status`: `none → pending → done|failed`
   (with `translation_model` recorded); failure marking distinguishes owned/unowned runs.

Other entry points in the same file: `translate_raw_text` (returns text without touching
the chapter — powers self-translate overlays), `prefetch_translations` (next
`TRANSLATE_PREFETCH`=3 pending raws after the one just opened),
`translate_range` (batch/CLI), `seed_glossary_from_entities` (pull canonical English
spellings from codex entities so a source switch keeps names stable), and the AGY
staging trio `stage_translation_batch` / `reset_staged_translations` /
`commit_translation` with `run_id` identity (`SourceChangedError` when the chapter moved
under a staged batch).

## Scheduling a batch (`application/scheduling.py`)

`TranslationSchedulingService.schedule(novel_id, principal, command)` — the HTTP
`POST /api/novels/{id}/translate` path:

1. Catalog editable check (port).
2. Count pending chapters in range (Reading port) — nothing to do ⇒ `InvalidOperation`.
3. Resolve execution backend (API vs AGY) via `BackendResolutionPort` (AI Execution).
4. Reserve quota for the pending count (`TranslationQuotaPort` → Identity).
5. Create-or-dedupe the durable Work job (`TranslationWorkPort`, idempotency-keyed).
6. Refund on failure or dedupe — the `schedule_ai_job` compensation shape (ADR 003).

The worker side then meters per chapter *as it actually translates*, so a canceled batch
keeps only what it finished charged.

## Surfaces

- **HTTP** (`adapters/inbound/http.py`): `POST /api/novels/{id}/translate` (batch),
  `GET/PUT /api/novels/{id}/glossary`, `DELETE …/glossary/{term_id}`,
  `POST …/glossary/seed`.
- **CLI** (`adapters/inbound/cli.py`): `translate <novel_id> --from --to [--force]
  [--seed]`.
- **Worker handler** (`adapters/inbound/jobs.py::execute_translation_job`): drives
  `translate_range` chapter-by-chapter under the generic Work worker with cancel checks
  between chapters.

## Outbound adapters

- `postgres.py::PostgresTranslationTransactionService` — glossary SQL (the owned table).
- `runtime.py` — the engine above (provider calls via the AI Execution chat gateway in
  the runtime bundle).
- `agy.py` — the AGY variant of a batch job: stage snapshot → build workspace input
  manifests (chapters + glossary) → run the AGY CLI per sub-batch
  (`AGY_TRANSLATE_BATCH_CHAPTERS`/`_MAX_CHARS`) → validate output artifacts (length/
  glossary-respect checks in `_validate_quality`) → commit through the *same*
  `commit_translation` workflow → `_resume_ready_commits` can commit completed artifacts
  after a crash without re-running the model.
- `scheduling.py` — the three bridges Bootstrap wires into the scheduling service's ports
  (`BackendResolutionBridge`, `TranslationWorkBridge`, `TranslationQuotaBridge`).

## Collaboration notes

- Reading owns every chapter write; Translation's only table is the glossary. The
  `commit_translation` workflow is the *only* place both change together.
- Quota kind: `translated_chapters` (default 1000/month). Self-translate overlays are
  metered to the *reader*, batch jobs to the requester.
- Codex ↔ Translation: `seed_established_terms` imports codex entity names; discovered
  terms flow the other way only through the glossary (no direct codex writes).
