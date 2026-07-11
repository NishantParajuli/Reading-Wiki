# 🌊 Tideglass

A self-hosted, **multi-user** reading platform for webnovels and ebooks. Bring a story in
from anywhere — **scrape** it chapter-by-chapter from a site, or **import** an EPUB/PDF (digital
*or* scanned) — and read it in a cozy, distraction-free reader. Raw foreign-language chapters
are **translated on demand** as you open them, any chapter can be **narrated as an audiobook**,
and any novel can opt into an agentic, **spoiler-gated codex** (a chapter-bounded knowledge base).

Multiple people can use one instance: each reader has their own account, library, reading
progress, and quotas. Novels can be kept **private**, **shared publicly**, or curated into a
**global** library that everyone can read.

---

## THE ONE INVARIANT (the codex)

The codex upholds a single, hard rule:

> When you are reading at **chapter N**, no information from any chapter **> N** may ever
> appear in a codex entry, a stat, or a Q&A answer.

That boundary is enforced at the **database and retrieval layers** (`WHERE chapter <= ceiling`
on every read) — never by trusting the LLM to hold back. The server computes each reader's
effective ceiling from trusted, server-observed chapter reads (`max_chapter_read`); browser
progress updates can move the resume position, but cannot unlock future codex data.

---

## ✨ What it does

### 📚 Library & accounts
- **Per-user libraries** — Every reader has their own shelves (`to_read` / `reading` / `completed`),
  reading progress, bookmarks, and synced reader preferences. One person's "reading" is another's
  "completed."
- **Accounts & auth** — Email + password (Argon2-hashed), opaque server-side sessions in an
  httpOnly cookie, email verification, password reset, and optional **Google / Discord OAuth**.
- **Profiles** — Public profile pages (`/u/<username>`) with reading stats, currently-reading,
  recently-finished, and published novels, plus an avatar.
- **Sharing & discovery** — A novel is `private`, `public`, or `global` (an admin-curated shared
  library). The **Discover** page browses the shared library; "add to library" lets many readers
  share one underlying text.
- **Admin dashboard** — Manage users (suspend / ban / promote / adjust quotas / delete),
  watch platform-wide monthly spend and top spenders, and moderate novels.
- **Quotas** — Anything that costs API money (translation, OCR, codex builds, narration) is
  metered per user per calendar month, with admin-adjustable per-user caps. A verified email is
  required to spend.

### 🏠 Home, jobs & operations
- **Continue home** — The first screen after login (`GET /api/home`) is operational, not marketing:
  *continue reading* / *continue listening* (novels with narration available), *active jobs*,
  *recent imports*, and the *newest shared novels*. It only ever surfaces novels you can actually
  read (owned, still-shared, or admin).
- **Unified job center** — One feed (`GET /api/activity`) over the three durable job systems
  (generic scrape/codex/translate + import + TTS), grouped by kind with stage/progress/error and a
  cancel button that dispatches to the right endpoint. Scoped to your own jobs (admins see all).
- **Cost estimates before you spend** — Expensive actions (codex build, batch translation,
  whole-book narration) show estimated units vs. your remaining monthly quota first
  (`GET /api/novels/{id}/cost-estimate`) — clear and concrete, never a surprise charge.
- **Discover filters & provenance** — Browse the shared library by language, translation type,
  status tag, *has codex*, *has audio*, and source freshness. Every novel/chapter carries
  **provenance badges** (scraped · imported · OCR'd · translated · edited · owner-approved).
- **Novel health panel** — Owners get a pipeline-health summary (`GET /api/novels/{id}/health`):
  codex missing/stale, untranslated raw chapters, missing narration for a voice, source freshness,
  and recent pipeline errors — without digging through logs.

### 🕸 Getting stories in
- **Multi-source scraping** — A novel can be stitched from several sources (e.g. an English site
  that ends at ch. 124 + a raw site that continues at 125). Each source carries a `chapter_offset`
  mapping its local numbering onto one continuous **global** sequence. Scraping is incremental and
  stops cleanly at premium/paywalled chapters. Built-in adapters cover several sites; new ones are
  a small subclass.
- **File import (EPUB / PDF)** — Upload (or drop into a watched folder) an EPUB or PDF. Digital
  PDFs and EPUBs are parsed directly; **scanned PDFs** are OCR'd (local PaddleOCR sidecar, with
  Gemini-vision escalation for low-confidence pages). Imports run as **durable, resumable jobs**
  with an editable segmentation plan you review before committing, a heuristic quality score,
  chunked uploads for big files, and **batch / multi-volume series** import.

### 🌐 Translation
- **On-demand + prefetch** — Opening a raw chapter translates it inline and prefetches the next
  few in the background, so reading flows without waiting at each boundary.
- **Per-novel glossary** — Recurring names/terms stay spelled the same across chapters and across
  a source switch (e.g. `林轩 → Lin Xuan` once, everywhere after). User-pinned (`locked`) terms are
  never overwritten.
- **Personal overlays & contribute-back** — On a shared novel, a reader can override a chapter's
  translation for their own account (an *overlay*) or self-translate it, then **offer it back** to
  the owner as a contribution. The owner merges or rejects it; when the shared base later changes,
  overlays forked from the old version are flagged as conflicts with a base-vs-mine resolver.

### 🎧 Audiobook narration (TTS)
- **Whole-book or per-chapter** — Narrate the chapter you're reading, or kick off a bounded,
  cancellable **whole-book** job. Audio is generated by a GPU sidecar (OmniVoice), cached as Opus,
  and streamed to a custom transport UI in the reader.
- **Consistent cloned voices** — Several shipped narrators (voice-cloned from a fixed reference
  clip each) keep one consistent voice across an entire book. Generation is a durable, resumable,
  quota-metered background job.

### 🧠 Spoiler-safe codex *(opt-in per novel)*
Chunk → embed → forward-only entity/fact/relationship extraction → hybrid retrieval → agentic
Q&A, all bounded to your current chapter. Browse entities, read synthesized profiles, follow
relationships and timelines, see identity-reveal banners only once the reveal chapter is within
your ceiling, and ask freeform questions with inline, popover-backed citations. A one-click
**no-spoiler recap** (`POST /api/novels/{id}/recap`) summarizes the story so far, cited and bounded
by the *same* server-trusted ceiling as the codex and Ask — the model never sees a chapter you
haven't read, and recaps are cached per `(novel, ceiling)`.

---

## 🏛 Architecture overview

The backend is a modular monolith: one deployable FastAPI process and one PostgreSQL database,
with business ownership divided among Identity, Catalog, Reading, Acquisition, Translation,
Codex, Narration, Work, AI Execution, and Experience. Each module exposes a small `public.py`
contract; HTTP/CLI/worker adapters call application use cases, while PostgreSQL, filesystem,
provider, and sidecar details live behind outbound adapters. Atomic cross-module operations are
named workflows coordinated by the composition root. See
[`docs/architecture/module-ownership.md`](docs/architecture/module-ownership.md).
The final ownership evidence and automated gates are recorded in
[`docs/architecture/migration-completion.md`](docs/architecture/migration-completion.md); deployment
and rollback steps are in [`docs/release-runbook.md`](docs/release-runbook.md).

```
   webnovel site ─► Scraper (adapter per site) ─┐
   EPUB / PDF ────► Importer (parse · OCR · ────┤─► chapters (global numbering;
                    segment · review · commit)   │   content / original_text / rich_html)
                                                 │
        ┌────────────────────────────────────────┼───────────────────────────────────────┐
        ▼                  ▼                      ▼                  ▼                      ▼
     READER          TRANSLATION             AUDIOBOOK            CODEX (opt-in)      MULTI-USER
  progress ·      on-demand + prefetch ·   durable TTS jobs ·  chunk → embed →     accounts · sessions
  bookmarks ·     per-novel glossary ·     OmniVoice GPU       forward-only        OAuth · quotas ·
  scroll ·        per-user overlays +      sidecar → cached    extraction          private/public/global ·
  themes · TOC    contribute-back          Opus → reader       (entities/facts/    overlays + contribute-back
                                                               relations/events)         │
                                                                          ┌──────────────┴──────────────┐
                                                                          │       RETRIEVAL LAYER        │
                                                                          │ BM25 (bm25s) ⊕ dense (pgvec) │
                                                                          │   → RRF → rerank + tools     │
                                                                          │  ── WHERE chapter <= N ──    │
                                                                          └──────────────┬──────────────┘
                                                                                  AGENTIC ORCHESTRATOR
                                                                          Pro plans → Flash distills →
                                                                          Pro reasons (loop, capped)
                                                                                         │
   FastAPI  ──►  React SPA (Library · Discover · Reader · Codex · Profile · Admin)   ◄── auth (cookie)

   Optional GPU sidecars (separate images):   OCR :8077 (PaddleOCR)   ·   TTS :8078 (OmniVoice)
```

---

## 🧰 Tech stack

- **Backend:** Python 3.12+, FastAPI + Uvicorn, `asyncpg`
- **Database:** PostgreSQL with `pgvector` (dense vectors / HNSW) and `pg_trgm` (fuzzy name matching)
- **Auth:** server-side sessions, `argon2-cffi` password hashing, hand-rolled Google/Discord OAuth
  (httpx only), `aiosmtplib` for transactional email
- **Retrieval:** `bm25s` (sparse/lexical) ⊕ pgvector (dense) → Reciprocal Rank Fusion → reranker
- **LLM:** [OpenRouter](https://openrouter.ai) — a "Flash reads, Pro thinks" split for
  extraction/Q&A, plus translation and segmentation models. Embeddings + reranking are configurable
  model IDs.
- **Vision / OCR:** PaddleOCR (PP-StructureV3) in a GPU sidecar + Gemini vision (OpenAI-compatible
  endpoint) as the quality escalation
- **TTS:** OmniVoice voice-cloning in a GPU sidecar; stored as Opus via `ffmpeg`
- **Scraping:** `curl-cffi` (TLS-fingerprint-resistant fetch) + `selectolax` / `lxml`, `json-repair`
- **File import:** `ebooklib` (EPUB), `pymupdf` (PDF), `nh3` (HTML sanitize), `pillow`, `ftfy`
- **Frontend:** React 18 + TanStack Query, built by Vite 6 and served as same-origin static files
  by FastAPI
- **Packaging:** `uv` (with `pyproject.toml` + `uv.lock`)

---

## 🚀 Getting started

### 1. Prerequisites
- **Python 3.12+** (and [`uv`](https://github.com/astral-sh/uv), recommended)
- **PostgreSQL** with the `vector` and `pg_trgm` extensions available
- An **OpenRouter API key** (translation, extraction, embeddings, reranking, Q&A, segmentation)
- *(Optional)* a **Gemini API key** for scanned-PDF OCR escalation
- *(Optional)* an **NVIDIA GPU** to run the OCR and/or TTS sidecars

### 2. Install dependencies

```bash
uv sync            # creates .venv and installs from uv.lock
# — or with pip —
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 3. Configure

```bash
cp .env.example .env
```

Then fill in `.env`. Key settings (see [novelwiki/config/settings.py](novelwiki/config/settings.py)
for the full list and defaults):

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | App DB connection (plain `postgresql://` — **not** the SQLAlchemy dialect form) |
| `DB_SUPERUSER_URL` | Superuser connection used to auto-create the DB on first run |
| `OPENROUTER_API_KEY` | Unified key for chat, translation, embeddings, and rerank calls |
| `MODEL_PRO` / `MODEL_FLASH` | Planner/reasoner vs. cheap reader/distiller (may be the same model) |
| `MODEL_TRANSLATE` / `SEGMENT_MODEL` | Raw-chapter translation / import segmentation models |
| `EMBED_MODEL` / `EMBED_DIM` | Embedding model and its vector dimension |
| `RERANK_MODEL` | Reranker model |
| `SESSION_SECRET` | Signs/peppers session tokens — **set a long random value in prod** |
| `ALLOWED_ORIGINS` / `PUBLIC_BASE_URL` / `COOKIE_SECURE` | CORS origins, link/redirect base URL, cookie scope |
| `AUTH_*_LIMIT` / `AUTH_*_WINDOW_SECONDS` | Login, registration, and password-reset abuse throttles |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_USERNAME` | First admin, bootstrapped on first run |
| `SMTP_*` | Transactional email (leave `SMTP_HOST` blank to log links instead of sending — handy in dev) |
| `GOOGLE_*` / `DISCORD_*` | OAuth client credentials (leave blank to hide the button) |
| `GEMINI_API_KEY` / `OCR_*` | Scanned-PDF OCR (Gemini vision + PaddleOCR sidecar) |
| `SCRAPER_TIMEOUT_SECONDS` / `SCRAPER_MAX_RESPONSE_MB` / `SCRAPER_REQUIRE_SAME_HOST` | Scraper network guardrails: timeout, response cap, and same-source host binding |
| `TTS_*` / `TTS_SIDECAR_URL` | Audiobook narration (OmniVoice sidecar) |
| `SIDECAR_AUTH_TOKEN` | Shared token the web app sends to the OCR/TTS sidecars; each enforces it (set a long random value in prod) |
| `DEFAULT_QUOTA_*` | Monthly per-user spend caps (translation / OCR / codex / TTS) |

> **Schema is auto-created.** On server startup (and CLI use) the app connects with
> `DB_SUPERUSER_URL`, creates the `novelwiki` database if missing, then applies idempotent DDL.
> You can also run it explicitly:
>
> ```bash
> python -m novelwiki.db.schema
> ```

### 4. Bootstrap the first admin

On first startup the app runs an **idempotent multi-user migration** that creates the admin from
`ADMIN_EMAIL` / `ADMIN_PASSWORD` and adopts any pre-existing (single-user) library as the admin's
global shelf. To run it explicitly and supervised:

```bash
python -m novelwiki.db.migrate_multiuser
```

> ⚠️ The migration rewrites existing data. **Take a `pg_dump` first** and test against a restored
> copy before running on a production DB with real content.

---

## 🌐 Running the server

```bash
uvicorn novelwiki.api.app:app --reload --host 0.0.0.0 --port 8000
# or simply:
python main.py            # serves on :8000
```

Open **http://localhost:8000**, register an account (or log in as the admin), and start adding
novels. The React SPA is served directly by FastAPI (no separate frontend build/server). The
browser only ever talks to the chapter-bounded, auth-gated API, so nothing past a reader's
ceiling reaches it.

**App surfaces:**
1. **Library** — your shelves, reading progress, and quick actions.
2. **Discover** — the shared (global/public) library; add a shared novel to read it.
3. **Novel detail** — manage sources (add/edit, set `chapter_offset`), trigger scraping, manage
   the translation glossary, review contributions/tag suggestions, set visibility, and build the codex.
4. **Reader** — the immersive reading view (themes, width, auto-scroll, bookmarks, scroll recovery,
   TOC with volume grouping, the audiobook transport, and per-chapter translation editing).
5. **Codex** *(if enabled)* — a chapter-ceiling slider plus Home stats, Browse/search entities,
   Entity pages (synthesized profile + facts + relationships + timeline + identity-reveal banners),
   and **Ask** (agentic Q&A with inline citations).
6. **Profile / Account** — public profile, reading stats, avatar, and account/quota settings.
7. **Admin** *(admins only)* — users, platform spend, and moderation.

---

## 🛠 Command-line interface

The CLI drives ingestion from the terminal. Invoke it as a module from the repo root:

```bash
python -m novelwiki.cli --help
```

```bash
# ── Scraping ──
# Create a novel + its first source (prints the new ids)
python -m novelwiki.cli add-novel "Example Novel" "https://fenrirealm.com/novel/example/chapter-1" --adapter fenrirealm
# Scrape (all sources, or one with --source); stops cleanly at premium
python -m novelwiki.cli scrape <novel_id> --max 50

# ── File import (EPUB / digital PDF) ──
python -m novelwiki.cli import path/to/book.epub                 # new novel (heuristic segmentation)
python -m novelwiki.cli import path/to/vol2.epub --novel <id> --offset 100   # append to an existing novel
python -m novelwiki.cli import-batch ~/Calibre --series          # bulk import a folder, grouping series
python -m novelwiki.cli import-series vol1.epub vol2.epub         # several volumes → one multi-volume novel
python -m novelwiki.cli import-worker                            # run the durable import worker standalone

# ── Translation ──
python -m novelwiki.cli translate <novel_id> --from 1 --to 50    # --seed pulls names from the codex first

# ── Codex pipeline (codex-enabled novels) ──
python -m novelwiki.cli chunk <novel_id>          # paragraph-aware chunking
python -m novelwiki.cli embed <novel_id>          # batch vector embeddings
python -m novelwiki.cli extract <novel_id>        # forward-only metadata extraction
python -m novelwiki.cli rebuild-bm25 <novel_id>   # build/refresh the per-novel BM25 index
python -m novelwiki.cli merge <novel_id> --keep <id> --drop <id>   # merge two duplicate entities

# Drop ALL tables and re-apply schema (destructive)
python -m novelwiki.cli reset-db
```

> The UI's codex **Build** button runs `chunk → embed → extract → rebuild-bm25` for you in the
> background; the CLI exposes each step individually. Scanned-PDF imports need the OCR cost-confirm
> gate and are done from the web UI, not the CLI.

---

## 🔌 Scraper adapters

Each source picks an adapter by key. Built-in adapters live in
[novelwiki/scraper/adapters.py](novelwiki/scraper/adapters.py):

`fenrirealm` · `readhive` · `boti-translations` · `69shuba` · `wetriedtls`

Add a new site by subclassing `BaseAdapter` (or `_PagedHtmlAdapter`) and registering it in the
`ADAPTERS` dict — it then appears automatically in the Add-Source dropdown via `list_adapters()`.

Scraper fetches are routed through `novelwiki/scraper/safe_fetch.py`: only HTTP(S) URLs are allowed,
DNS results and redirects must resolve to public addresses, response bodies are capped, and crawls are
bound to the source host unless an adapter declares an explicit `allowed_hosts` exception. The default
`SCRAPER_REQUIRE_SAME_HOST=true` also blocks cross-host redirects, including CDN/API hops; adapter
authors should add known secondary hosts on the adapter class, e.g. `allowed_hosts = ["api.example.com"]`,
instead of disabling same-host checks globally.

---

## 📥 File import pipeline

Uploaded EPUB/PDF files flow through a durable, resumable job (state in `import_jobs`, big artifacts
on disk) so an import survives a deploy/restart and a multi-day OCR run survives the Gemini
free-tier quota. The pipeline:

1. **Upload** (single-shot up to `MAX_UPLOAD_MB`, or a resumable chunked upload up to
   `MAX_CHUNKED_UPLOAD_MB` for big files) or drop into the watched `IMPORT_INCOMING_DIR`. Chunked
   uploads are bounded up front (declared size capped at init) and append-only — each chunk must
   land contiguously at the resume cursor and stay within the declared total, so a client can't
   punch gaps, forge a sparse file, or exhaust disk; completion is verified and hashed by
   streaming (never loaded whole into memory). Abandoned `receiving` sessions are GC'd after
   `IMPORT_UPLOAD_SESSION_TTL_HOURS`.
2. **Parse** to a normalized block-stream IR — EPUB XHTML, digital-PDF spans, or OCR blocks.
   Scanned PDFs are OCR'd by the PaddleOCR sidecar with **Gemini-vision escalation** for
   low-confidence pages (and a cost-confirm gate before any paid OCR).
3. **Segment** into a draft plan (heuristics first — spine/headings — then an optional cheap LLM
   refinement of kinds/titles/numbers), with a **quality score**.
4. **Review** the plan in the UI (rename/renumber/include-exclude segments, group volumes).
5. **Commit** included segments into `chapters` through the same path the scraper uses — so codex,
   translation, and narration work on imported books with zero extra wiring. CJK-detected scans are
   flagged as a raw source and flow into translation.

The worker claims jobs atomically (`UPDATE … FOR UPDATE SKIP LOCKED`, each trigger status moving to
a distinct in-progress marker) and stamps a **leased claim** (`claim_token` + `claimed_at`), which it
renews on a heartbeat while it works — so the same job is never double-processed, safe to run more
than one worker. Recovery is purely lease-expiry based (`IMPORT_LEASE_TIMEOUT_SECONDS` /
`IMPORT_WORKER_HEARTBEAT_SECONDS`): an in-progress job is requeued only once its lease goes unrenewed,
i.e. its owning worker is provably gone. There is deliberately no "requeue everything on boot" step —
that would reclaim work a sibling worker is actively processing.

---

## 🎧 Audiobook narration (TTS sidecar)

Narration runs on a **separate GPU sidecar** (OmniVoice, on `:8078`) so the web image stays
GPU-free. A durable, DB-polled worker advances narration jobs one chapter at a time, caches the
result as Opus, and the reader streams it. Voices are cloned from a fixed reference clip so a whole
book gets one consistent narrator; see [sidecar-tts/voices/README.md](sidecar-tts/voices/README.md)
to add your own (use public-domain / consented audio only).

```bash
docker compose up -d tts        # start the TTS sidecar on a GPU host
```

---

## ⚙️ Background jobs & observability

Scraping, codex builds, and translation batches run as **durable jobs** (state in the generic
`jobs` table), not fire-and-forget `BackgroundTasks` — so the work survives a deploy/restart even
after quota was reserved, and a repeated click dedupes onto the already-active job instead of
double-charging. A third DB-polled worker ([novelwiki/jobs/worker.py](novelwiki/jobs/worker.py))
claims them with the same leased-claim model as the import worker (`FOR UPDATE SKIP LOCKED` +
`claim_token`/`claimed_at` heartbeat, lease-expiry recovery via `JOB_LEASE_TIMEOUT_SECONDS` /
`JOB_WORKER_HEARTBEAT_SECONDS`), retries a crashed attempt up to `JOB_MAX_ATTEMPTS`, and cancels
cooperatively (a running job stops before its next expensive stage, keeping what it finished).

**Quota is explicit and refundable.** A job records what it reserved (`quota_reserved`) and used
(`quota_consumed`); the worker finalizes exactly once at a terminal state — a successful codex build
keeps its credit, while a failed or cancelled one refunds it (`quota.refund`, clamped so usage never
goes negative). Translation meters per chapter as it actually translates, so a cancelled batch keeps
the chapters it finished charged and never over-charges for ones it didn't reach.

**Job center + audit.** Owners/admins see active and recent jobs (status, stage, live progress) and
can cancel one in flight — in the novel page UI, or via `GET /api/jobs`, `GET /api/jobs/{id}`,
`POST /api/jobs/{id}/cancel` (non-admins are scoped to their own jobs; admins can filter by
kind/status/user/novel). A **unified job center** (`GET /api/activity`) additionally folds the
import and TTS job systems into one feed for the *Jobs* page and the Continue home, so a reader sees
all their background work — scrapes, imports, codex, translation, narration — in one place. Every
response carries an `X-Request-ID` (accepted from a trusted proxy or minted), and job lifecycle +
quota refunds are written to a durable `audit_events` log stamped with that request id, so a single
user action is traceable across the request and the jobs it spawned.

---

## 🗄 Data model

Everything is **novel-scoped and user-scoped** (single shared Postgres DB, no schema-per-novel).
Schema is defined in [novelwiki/db/schema.py](novelwiki/db/schema.py):

- **Accounts:** `users`, `oauth_accounts`, `sessions`, `email_tokens`, `auth_rate_limits`,
  `quota_usage`, `provider_budget`
- **Catalog:** `novels` (with `owner_id` / `visibility` / `contribution_policy` / `series`),
  `library_entries` (per-user shelf + tags), `tag_suggestions`
- **Acquisition:** `sources`, `import_jobs`, `assets` (content-addressed images on disk)
- **Reading:** `chapters` (PK `(novel_id, number)`; `content` = readable text, `original_text` =
  source language, `raw_html` = sanitized rich HTML for imports, `content_version` anchors overlays;
  `kind` / `part_label` for import structure), `reading_progress`, `bookmarks`, `chapter_overlays`,
  `contributions`
- **Translation:** `translation_glossary`
- **Audiobook:** `tts_jobs`, `chapter_audio` (shared base + per-user audio cache)
- **Codex:** `chunks` (+`embedding`), `entities`, `entity_descriptions`, `entity_aliases`,
  `identity_links`, `entity_facts`, `relationships`, `events`, `extraction_state`, `wiki_cache`,
  `query_cache`
- **Ops:** `jobs` (durable scrape/codex/translation jobs with quota reserve/refund state),
  `audit_events` (job lifecycle + quota refunds, stamped with the request id)

Imported covers/illustrations/page scans are stored on disk but served through authenticated
`/api/assets/novels/...` and `/api/assets/import-jobs/...` routes. Only user avatars remain on the
narrow public `/assets/_users/...` mount. SVG imports are rejected, and the app sets baseline
`nosniff`, frame, referrer, and CSP headers. The SPA is precompiled, uses self-hosted fonts, and
does not require CDN scripts or runtime `eval`.

---

## 🧪 Testing

Spoiler boundaries, import pipelines, module boundaries, and the multi-user layer are verified
with `pytest`. The launcher maps the configured Docker database hostname for host-side execution:

```bash
uv run python scripts/test_backend.py
uv run pytest -q tests           # architecture/contracts only; no database required
# or target a suite directly, e.g.:
uv run pytest novelwiki/eval/spoiler_tests.py
uv run pytest novelwiki/eval/import_tests.py novelwiki/eval/multiuser_regression_tests.py
```

> The suites isolate themselves to disposable test databases — they never touch your real DB.

Frontend compatibility tests and the production build run with:

```bash
cd novelwiki/frontend
npm test
npm run build
```

---

## 🐳 Docker & deployment

A multi-stage [Dockerfile](Dockerfile) builds a `uv`-synced runtime image (non-root, serves on
**:8001**). The source and frontend are **baked into the image at build time** — only `/app/data`
(BM25 indexes, import scratch, extracted assets, generated audio) is a persistent volume, so
deploying changes means rebuilding the image.

```bash
docker compose up -d --build          # web app only
docker compose up -d ocr              # + OCR sidecar (GPU; scanned PDFs)
docker compose up -d tts              # + TTS sidecar (GPU; audiobooks)
```

`docker-compose.yml` puts every service on a **private bridge network** (`novelwiki_net`). The web
container reaches the sidecars by service DNS (`http://ocr:8077`, `http://tts:8078`); the sidecar
ports are **never published to the host**, so the expensive `/ocr`, `/synthesize`, and `/narrate`
endpoints can't be reached from outside — and on top of that they require a **shared service token**
(`SIDECAR_AUTH_TOKEN`) that the web app sends and each sidecar enforces. The web port is published
**loopback-only** (`127.0.0.1:8001`) so the Cloudflare tunnel on the host fronts it while public
interfaces can't. The two GPU sidecars are **optional and independent** — the web app runs fine
without them (digital imports and reading work; scanned-PDF OCR and audiobook jobs simply require
their sidecar). On a single small GPU, run only the sidecar you're actively using. In production the
app sits behind a Cloudflare tunnel (set `ALLOWED_ORIGINS` / `PUBLIC_BASE_URL` to your domain and
keep `COOKIE_SECURE=true`).

> **Host PostgreSQL:** off host networking, `localhost` inside a container is the container itself.
> The `web` service maps `host.docker.internal` to the host gateway, so point `DATABASE_URL` /
> `DB_SUPERUSER_URL` at `host.docker.internal:5432` (e.g.
> `postgresql://user:pass@host.docker.internal:5432/novelwiki`).
>
> **Service token:** set a long random `SIDECAR_AUTH_TOKEN` in `.env` before starting the sidecars.
> If no token is configured, `/ocr`, `/synthesize`, and `/narrate` fail closed. For local-only
> experiments on a private loopback bind, set `SIDECAR_ALLOW_UNAUTHENTICATED=1` deliberately.
>
> **Fallback if host networking is unavoidable:** keep `SIDECAR_AUTH_TOKEN` set, leave the sidecars
> bound to loopback (`UVICORN_HOST=127.0.0.1`, the image default), and add firewall rules dropping
> `8077`/`8078` (and public `8001`) on public interfaces.
