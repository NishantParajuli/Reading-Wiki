# Acquisition module (`novelwiki/modules/acquisition/`)

**Responsibility:** getting story text *into* the system: multi-source **scraping** with
per-site adapters and SSRF-hardened fetching, the durable **EPUB/PDF import** pipeline
(upload → parse → OCR → segment → review → commit), and the extracted-image **asset**
store. Pipeline walkthroughs live in
[../pipelines/scraping.md](../pipelines/scraping.md) and
[../pipelines/file-import.md](../pipelines/file-import.md); this page covers the module's
shape.

**Owned tables:** `sources`, `import_jobs`, `assets`.
**Owned filesystem roots:** `IMPORT_DIR` (job artifacts, block streams, upload scratch),
`ASSET_DIR/<novel_id>/` (extracted images; served via access-controlled routes).

---

## Public contract (`public.py`)

- **`SourceDraft`** — `(adapter, start_url, language, is_raw, chapter_offset, label,
  config)` for source creation.
- **`ImportNovelDraft`** — how an import describes the novel it wants created.
- **`AcquisitionTransactionApi`** — workflow-bound capability used by
  `create_novel_with_source`, `delete_novel`, `update_source_offset`, and
  `commit_import`: `create_source`, `list_import_job_ids`, `store_novel_asset`,
  `source_offset_state`/`set_source_offset`, `import_source`/`replace_import_source`/
  `create_import_source`, `commit_import_asset`, `finalize_import_job`.
- **`AcquisitionCleanupApi`** — post-commit filesystem cleanup for a deleted novel.
- **`AcquisitionApi`** — `list_cleanup_targets`, `cancel_import`.

## Structure

### Inbound adapters

- **`http.py`** — the import/scrape/source HTTP surface:
  - sources: `POST /api/novels/{id}/sources`, `PATCH …/sources/{sid}` (offset changes run
    the `update_source_offset` workflow), `GET /api/adapters` (registry for the UI
    dropdown), `POST /api/novels/{id}/scrape` (schedules a durable Work job).
  - uploads: `POST /api/import/upload` (single-shot ≤ `MAX_UPLOAD_MB`);
    resumable chunked uploads — `init` → `PUT …/{job_id}/chunk` (contiguous,
    size-capped, append-only) → `complete` (streamed hash verification) → `status`;
    `POST /api/import/scan-incoming` (watched-folder pickup);
    `POST /api/import/batch`, `POST /api/import/commit-series` (create a new grouped
    series or append the ordered jobs to an existing editable novel).
  - job lifecycle: `GET /api/import/jobs`, `GET/DELETE …/jobs/{id}`,
    `PUT …/jobs/{id}/plan` (edit the segmentation plan and authoritative book/series/
    volume metadata), `POST …/confirm-ocr` (the paid OCR cost-confirm gate),
    `POST …/commit`, `POST …/cancel`.
  - assets: `GET /api/assets/novels/{novel_id}/{filename}` and
    `GET /api/assets/import-jobs/{job_id}/{filename}` — **access-controlled** streaming
    (Catalog readable-check / job ownership) so private-novel images never leak via a
    public static mount.
- **`cli.py`** — `add-novel`, `scrape`, `import`, `import-batch`, `import-series`,
  `import-worker` (Typer transports; logic in application commands).
- **`worker.py::ImportWorkerAdapter`** — the in-process durable import worker
  (start/stop from the lifecycle; also runnable standalone via the CLI).
- **`jobs.py::execute_scrape_job`** — the generic-worker handler for `kind='scrape'`.

### Application

- **`sources.py` / `commands.py`** — source CRUD + scrape orchestration/scheduling
  (idempotency key per novel/source; stops cleanly at premium walls).
- **`imports.py`** — upload session state machine (`receiving` → `uploaded`), plan
  and validated metadata-override editing, cost estimation, commit preparation, series
  grouping, and target authorization for single- or multi-volume appends.
- **`import_worker.py`** — the durable import state machine (docstring is the canonical
  spec): trigger statuses `uploaded`/`ocr_pending`/`committing` are claimed atomically
  (`FOR UPDATE SKIP LOCKED`) into distinct in-progress markers
  `parsing`/`ocr_running`/`commit_running`; leased claims with heartbeats; lease-expiry
  recovery only (no requeue-on-boot); `ocr_paused` budget holds; owner-spend re-checks
  before paid work; one `asyncio.Lock` serializing OCR (one GPU).
- **`render.py`** — block-stream IR → reader HTML (sanitized via nh3) + plain text.
- **`runtime_dependencies.py`** — the immutable runtime bundle (parsers, OCR client,
  segmentation LLM, storage, Reading ingestion gateway, catalog/workflow factories,
  quota checks) built by `bootstrap/acquisition_runtime.py`.

### Domain

`document.py` (the normalized block-stream IR every parser emits: headings, paragraphs,
images, page markers), `quality.py` (segmentation quality scoring), `cleanup.py` (text
normalization: ftfy, encoding repair, boilerplate stripping, and geometry-aware PDF
cross-page paragraph rejoining).

### Outbound adapters

- **`scraper/`** — `adapters.py` (the site-adapter registry: `fenrirealm`, `readhive`,
  `boti-translations`, `69shuba`, `wetriedtls`; new sites subclass `BaseAdapter` or
  `_PagedHtmlAdapter` and register in `ADAPTERS`), `runner.py` (incremental scrape loop:
  resume URL from Reading, fetch → parse → `upsert_ingested_chapter`, premium-wall
  detection, `touch_novel`), `safe_fetch.py` (the SSRF boundary: HTTP(S)-only, public-IP
  DNS pinning, redirect re-validation, response size caps, same-host binding with
  adapter-declared `allowed_hosts` exceptions).
- **`importer/`** — `parsers/epub.py` (ebooklib; spine + XHTML + images),
  `parsers/pdf_text.py` (pymupdf digital-PDF spans, release-filename volume metadata,
  safe bare-`Vol N` detection, cover/illustration anchoring, tiny-decoration filtering),
  `parsers/pdf_ocr.py` (rasterize →
  PaddleOCR sidecar → Gemini-vision escalation for pages under
  `OCR_CONFIDENCE_ESCALATE`), `segment.py` (heuristic spine/heading segmentation +
  optional LLM refinement of kinds/titles/numbers), `storage.py` (job directories,
  block-stream persistence, `ensure_dirs`), `commit.py` (applies saved user metadata,
  then prepares the operation handed to the `commit_import` workflow), `ocr_client.py`
  (sidecar HTTP with the shared service token + provider budget).
- **`postgres.py`** — the owned-tables repository (import jobs, sources, assets).
- **`catalog_workflows.py`** — `PostgresAcquisitionTransactionService` (the
  `AcquisitionTransactionApi` implementation).
- **`scheduling.py` / `worker_jobs.py`** — Work-facing bridges (schedule scrape jobs,
  find-active dedupe) and import-worker persistence.
- **`adapter_catalog.py`** — `list_adapters()` for the UI.
- **`assets.py`** — content-addressed image storage (`sha256`, per-novel dedup via
  `UNIQUE (novel_id, sha256)`), dimension probing.

## Collaboration notes

- **All ingested text funnels through Reading's `upsert_ingested_chapter`** — scraper and
  import commit alike; that is why codex/translation/narration work identically on
  scraped and imported books.
- Import commits are atomic across Acquisition+Catalog+Reading+Codex via the
  `commit_import` workflow (novel/source creation, chapters, assets, codex invalidation,
  job finalization).
- Scrapes/imports are quota-relevant only via OCR (`ocr_pages`); scraping itself is free.
- CJK-detected scans set the source `is_raw`, feeding straight into translation.
