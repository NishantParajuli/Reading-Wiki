# Pipeline: translation

> How a raw (foreign-language) chapter becomes readable English, with names kept
> consistent, money metered fairly, and every commit atomic. Module reference:
> [../modules/translation.md](../modules/translation.md).

## Triggers (all converge on one engine)

| Trigger | Path | Metered to |
|---|---|---|
| Reader opens a pending raw chapter | `GET /api/novels/{id}/chapter/{n}` → inline translate + background **prefetch** of the next `TRANSLATE_PREFETCH` (3) | the reader |
| Manual batch | `POST /api/novels/{id}/translate` (range) → durable Work job | the requester |
| CLI | `translate <novel> --from --to [--seed]` | system/exempt |
| Self-translate (shared novel) | `POST …/chapter/{n}/self-translate` → the reader's **overlay**, base untouched | the reader |
| AGY batch | same durable job, `execution_backend='agy'` | the requester |

Quota kind: `translated_chapters` (default 1000/month). A verified email is required to
spend.

## The engine (per chapter)

1. **Lock** `(novel, chapter)` — concurrent triggers (reader + prefetch + batch) collapse
   onto one run; `translation_status` moves `none → pending`.
2. **Glossary in** — `translation_glossary` rows split into hard mappings
   ("always render 林轩 as Lin Xuan" — `locked` rows are user-pinned and inviolable) and
   established spellings (soft guidance). `--seed`/`POST …/glossary/seed` pre-populates
   English spellings from codex entities so a source switch (fan TL site → raw) keeps
   names identical.
3. **Model call** — `MODEL_TRANSLATE` via OpenRouter with the domain prompt; input
   capped at `TRANSLATE_MAX_INPUT_CHARS` (48k chars). The response is delimiter-framed:
   translated title, translation body, and a `new_terms` list (terms the model
   encountered and how it rendered them).
4. **Atomic commit** — the **`commit_translation` workflow** (Reading + Translation +
   Work in one transaction):
   - Reading: row-locked optimistic commit — the chapter's current
     `sha256(original_text)` must equal the hash snapshotted at translation start
     (`expected_source_hash`) and `content_version` must match; then `content`,
     translated title, `is_translated`, `translation_status='done'`,
     `translation_model` land and the version bumps. A concurrent re-scrape/edit ⇒ the
     commit refuses rather than overwrite; an identical replay ⇒ `{"idempotent": true}`.
   - Translation: `new_terms` folded into the glossary — **never overwriting existing
     rows** (first rendering wins; `locked` always wins).
   - Work: `quota_consumed += 1` on the driving job, *inside the same transaction* — a
     canceled batch keeps exactly the chapters it finished charged, never more.
5. **Failure** — `translation_status='failed'` (retryable; `failed` chapters count as
   pending for the next run unless `force` semantics say otherwise).

## Batch scheduling (HTTP)

`TranslationSchedulingService`: editable check → fast active-job dedupe → resolve backend
(API vs AGY per the user's grant) → count pending → quota guard → create/dedupe the
durable job (idempotency key over novel+range). AGY reserves the pending count up front
and finalization refunds the unconsumed remainder. API merely checks availability at
scheduling, then reserves/refunds one unit inside each per-chapter execution; therefore
it has no batch reservation. A zero pending count is a valid no-op job because the worker
recomputes the range at execution time.

## The AGY variant

Staging gives the subscription backend the same safety the API path gets from its
in-transaction hash check: `stage_translation_batch` snapshots and marks each chapter
with a `translation_run_id` + `translation_source_sha256` **before** any AGY work;
workspace manifests carry chapters + glossary; the CLI runs per sub-batch
(`AGY_TRANSLATE_BATCH_CHAPTERS`=3, ≤ `AGY_TRANSLATE_BATCH_MAX_CHARS`); output artifacts
are validated (schema, length sanity, glossary respect) and committed through the *same*
workflow keyed by the run id — a crashed/retried batch can't commit a chapter staged by
another run (`SourceChangedError`), and `_resume_ready_commits` salvages complete
artifacts after a worker loss without re-running the model. Capacity exhaustion parks
the job `waiting_provider`; permanent failure can fall back to the API backend
(releasing AGY's unused reservation first). See [ai-backends.md](ai-backends.md).

## Collaboration layer on top

Shared novels add per-reader **overlays** and **contribute-back** (Reading's tables and
routes — walkthrough in [../modules/reading.md](../modules/reading.md)): a reader can
override a chapter for themselves (`manual_edit` or `self_translated`), offer it to the
owner, and resolve conflicts when the shared base moves (`base_version` vs
`content_version`). Accepted contributions become the base (version bump → other
overlays flagged, audio cache invalidated).

## Reading experience guarantees

- Opening a raw chapter never blocks on the *next* ones — prefetch fills ahead.
- `original_text` is preserved forever: re-translation (e.g. after glossary fixes, with
  `force`) never needs a re-scrape.
- Provenance: `translation_model` + status surface as badges; the health panel counts
  untranslated raws; cost-estimate shows units before a batch.
