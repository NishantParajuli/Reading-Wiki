# Pipeline: file import (EPUB / PDF)

> How an uploaded book becomes chapters: upload → parse → (OCR) → segment → review →
> commit. Everything is a **durable, resumable job** (`import_jobs` + on-disk artifacts)
> because a deploy kills in-process work and a scanned-PDF OCR run can span days under
> the Gemini free tier. Module reference:
> [../modules/acquisition.md](../modules/acquisition.md).

## State machine (contract-frozen in `job_states.json`)

```
 receiving ──complete──▶ uploaded ──claim──▶ parsing ──▶ awaiting_review
 (chunked upload)                                              │ user commits
                                                               ▼
                     ocr_pending ──claim──▶ ocr_running    committing ──claim──▶ commit_running ──▶ committed
                        ▲    │ budget hold                     ▲
                        │    ▼                                 │
                        └─ ocr_paused ─(quota returns)─────────┘
 any state ──▶ failed | canceled          (stale lease ⇒ marker resumes to its trigger:
                                           parsing→uploaded, ocr_running→ocr_pending,
                                           commit_running→committing)
```

Trigger statuses (`uploaded`, `ocr_pending`, `committing`) are claimed atomically
(`FOR UPDATE SKIP LOCKED`) into distinct in-progress markers with a leased
`claim_token`/`claimed_at` heartbeat — the same pattern as the generic Work worker
([background-jobs-and-quota.md](background-jobs-and-quota.md)); recovery is purely
lease-expiry-based.

## 1. Getting the file in

Three entry paths, all ending at status `uploaded` with the blob under `IMPORT_DIR`:

- **Single-shot** `POST /api/import/upload` (multipart, ≤ `MAX_UPLOAD_MB` = 50).
  The browser picker accepts several EPUB/PDF files and queues each as its own reviewable
  job; large files independently switch to the chunked path below.
- **Resumable chunked upload** for big files (client switches above
  `UPLOAD_CHUNKED_THRESHOLD_MB` = 40): `init` (declares size, capped at
  `MAX_CHUNKED_UPLOAD_MB` = 1024; job starts as `receiving`) → `PUT …/chunk` repeatedly —
  each chunk ≤ `UPLOAD_CHUNK_MAX_MB`, must land **contiguously at the resume cursor**
  and stay within the declared total (append-only: no gaps, no sparse-file forgery, no
  disk exhaustion) → `complete` verifies and SHA-256-hashes by **streaming** (never
  loading the file into memory) → `uploaded`. Abandoned `receiving` sessions are GC'd
  after `IMPORT_UPLOAD_SESSION_TTL_HOURS` (24). Attack coverage:
  `eval/upload_security_tests.py`.
- **Watched folder** — drop into `IMPORT_INCOMING_DIR`, then
  `POST /api/import/scan-incoming`.

Plus batch forms: `POST /api/import/batch` (a server folder of books;
`--series`-style grouping) and `POST /api/import/commit-series`. The latter accepts
`job_ids` plus an optional `novel_id`: omit the target to create one multi-volume novel,
or provide an editable target to append the ordered batch after its current final chapter.

## 2. Parse → block-stream IR

The worker claims `uploaded → parsing` and produces a normalized **block-stream IR**
(`domain/document.py`: headings, paragraphs, images, page markers — persisted on disk,
not in the DB):

- **EPUB** (`parsers/epub.py`, ebooklib) — spine order, XHTML → blocks, images extracted
  as content-addressed assets, metadata (title/author/language/series) detected.
- **Digital PDF** (`parsers/pdf_text.py`, pymupdf) — text spans → blocks with heading
  heuristics from font geometry. Cleanup rejoins a paragraph split only by a physical
  page, dehyphenates/reflows hard-wrapped lines, and strips running page chrome. The
  parser ignores tiny bitmap rules/masks that would otherwise become empty reader
  figures, removes malformed outline-page footer glyphs, keeps full-page illustrations
  in reading order, and promotes the first full-page image to the cover. When embedded
  metadata is empty, a release filename such as `Series_02 [Publisher].pdf` supplies the
  series, index, and `Volume 2` label. A bare `Vol 2.pdf` safely supplies only the index
  and label—the parser does not invent a series name.
- **Scanned PDF** (`parsers/pdf_ocr.py`) — pages rasterized and OCR'd. Route: local
  **PaddleOCR sidecar** first (`OCR_SIDECAR_URL`, PP-StructureV3); any page whose mean
  confidence < `OCR_CONFIDENCE_ESCALATE` (0.80) escalates to **Gemini vision**
  (batched `GEMINI_PAGES_PER_REQUEST`, RPM-limited, and bounded by the *persistent*
  daily budget in `provider_budget` — exhaustion parks the job `ocr_paused`, resumed
  automatically next day). Before any *paid* OCR the job stops at `ocr_pending` with a
  `cost_estimate` until the owner consents via `POST …/confirm-ocr` (`ocr_pages` quota
  metered). Text detected as CJK marks the import raw → flows into translation later.

Rich output (`application/render.py`): sanitized HTML (nh3) with inline images for the
reader's rich mode + plain text for pipelines.

## 3. Segment → plan (+ quality score)

`outbound/importer/segment.py` builds a **draft plan**: heuristics first (EPUB spine +
heading patterns; PDF headings/page breaks), then an optional cheap LLM refinement
(`SEGMENT_MODEL`) of segment kinds/titles/numbers. The plan — a small editable JSON on
the job row — lists segments with `kind` (`chapter`/`frontmatter`/`interlude`/
`backmatter`), title, number, include flag, and volume grouping (`part_label`), plus a
heuristic **quality score** (`domain/quality.py`) so the UI can warn "this segmentation
looks off". Status: `awaiting_review`.

## 4. Review

The user edits the plan and book details in the Import UI
(`PUT /api/import/jobs/{id}/plan`). Title, author, description, language, series name,
volume number, and volume/group label are all user-editable; saved values are durable
job metadata overrides and take precedence over embedded EPUB/PDF metadata and filename
guesses in both single-job and multi-job commits. Segment title/number/kind/include and
each segment's `part_label` are editable too, so an unusual file can be corrected without
renaming or rebuilding it. Raw status and the target (new novel vs append/replace) remain
commit choices.

A detected series defaults to **group as volume**:
creating volume 1 uses the series as the novel title and writes its `part_label`; a later
matching upload preselects that editable novel, computes the next global numbers, and
uses the detected volume label. Turn volume grouping off to use the manual append offset.
For files named only `Vol 1`, `Vol 2`, and so on, enter and save the intended common
series name on each review; those jobs can then be selected and committed as a new series
or appended as one ordered batch. Nothing is committed until that action.

## 5. Commit (atomic)

`POST /api/import/jobs/{id}/commit` → `committing`; the worker claims it and executes
one **`commit_import` workflow** transaction across the four owners: Catalog
(create/append the novel, `series`, cover-if-missing), Acquisition (create/replace the
import source; register content-addressed assets), Reading (upsert every included
segment through the same funnel the scraper uses — `kind`, `part_label`, version
preservation, overlay-conflict marking on replaced chapters), Codex (invalidate
chapter-range artifacts). Then `finalize_import_job` stamps stats → `committed`.
Because committed chapters are ordinary chapters, codex/translation/narration work on
imported books with zero extra wiring. (`IMPORT_AUTO_BUILD_CODEX=true` additionally
schedules a codex build.)

## Operating notes

- One OCR at a time (an `asyncio.Lock` — a single GPU behind the sidecar), and the
  worker re-checks the owner may still spend before each paid stage.
- `DELETE /api/import/jobs/{id}` removes a terminal job + artifacts; `cancel` stops an
  active one cooperatively.
- The standalone worker (`python -m novelwiki.cli import-worker`) is lease-safe next to
  the in-process one.
- Watch it all in the Import screen or `GET /api/activity`; failures carry `error` +
  `stage`. Eval suites: `import_tests.py`, `import_pdf_tests.py`, `import_s4_tests.py`.
