# 🌊 Tideglass

A self-hosted, **multi-user** reading platform for webnovels and ebooks. Bring a story in
from anywhere — **scrape** it chapter-by-chapter from a site, or **import** an EPUB/PDF
(digital *or* scanned) — and read it in a cozy, distraction-free reader. Raw
foreign-language chapters are **translated on demand** as you open them, any chapter can
be **narrated as an audiobook**, and any novel can opt into an agentic, **spoiler-gated
codex** (a chapter-bounded knowledge base).

Multiple people share one instance: each reader has their own account, library, reading
progress, and monthly quotas. Novels can be kept **private**, shared **public**, or
curated into a **global** library everyone can read.

> **📚 Full documentation lives in [`docs/`](docs/README.md)** — architecture deep dives,
> a per-module reference, pipeline walkthroughs, the complete API/CLI/schema/config
> references, and a from-first-principles primer for newer developers. This README is
> the short version.

---

## THE ONE INVARIANT (the codex)

> When you are reading at **chapter N**, no information from any chapter **> N** may
> ever appear in a codex entry, a stat, a Q&A answer, or a recap.

That boundary is enforced at the **database and retrieval layers** (`WHERE chapter <=
ceiling` on every read) — never by trusting the LLM to hold back. The server computes
each reader's ceiling from trusted, server-observed chapter reads
(`max_chapter_read`); browser progress updates can move the resume position but cannot
unlock future codex data. Full model:
[docs/concepts/spoiler-safety.md](docs/concepts/spoiler-safety.md).

---

## ✨ What it does

- **📚 Library & accounts** — per-user shelves/progress/bookmarks/synced prefs; email +
  password (Argon2) with server-side sessions, email verification, password reset, and
  optional Google/Discord OAuth; public profiles (`/u/<username>`); private/public/global
  sharing with a **Discover** browser; an admin dashboard (users, platform spend,
  moderation); and **monthly quotas** on everything that costs API money.
- **🏠 Operational home** — continue reading / continue listening, a **unified job
  center** over all three durable-job systems, **cost estimates before you spend**,
  Discover filters + provenance badges, and a per-novel pipeline **health panel**.
- **🕸 Scraping** — a novel stitched from several sources (each with a `chapter_offset`
  mapping onto one **global** chapter sequence); incremental, stops cleanly at
  paywalls; per-site adapters (`fenrirealm`, `readhive`, `boti-translations`,
  `69shuba`, `wetriedtls` — new sites are a small subclass); SSRF-hardened fetching.
- **📥 File import** — EPUB and digital/scanned PDF as **durable, resumable jobs**:
  chunked uploads for big files, local PaddleOCR + Gemini-vision escalation (with a
  cost-confirm gate), an **editable segmentation plan** you review before committing,
  quality scoring, batch/series import. Committed chapters flow through the same funnel
  as scraped ones — codex/translation/narration need zero extra wiring.
- **🌐 Translation** — on-demand + background prefetch; a per-novel **glossary** keeps
  names consistent across chapters and source switches (`林轩 → Lin Xuan` everywhere,
  user-pinned terms never overwritten); per-reader **overlays** on shared novels with
  **contribute-back** review and conflict resolution.
- **🎧 Audiobooks** — per-chapter or bounded whole-book narration on a GPU sidecar
  (OmniVoice voice cloning — one consistent narrator per book), cached as Opus,
  streamed with scrubbing; charged only on actual generation.
- **🧠 Codex** *(opt-in per novel)* — chunk → embed → **forward-only** extraction →
  hybrid retrieval (BM25 ⊕ pgvector → RRF → rerank) → agentic **Ask** with inline
  citations; entity profiles, timelines, identity-reveal banners; one-click no-spoiler
  **recap** — all bounded by the same trusted ceiling and cached per ceiling.
- **⚙️ Durable pipelines** — scrapes, imports, codex builds, translation batches, and
  narration survive restarts as database-backed jobs with dedupe and cooperative
  cancellation. Generic Work jobs and imports use claim leases and heartbeats; the TTS
  queue is a deliberately single-instance, idempotent worker. Generic metered jobs settle
  quota exactly once, while TTS charges only audio actually generated. Codex builds and
  translation batches can optionally use the **AGY** subscription backend instead of the
  metered API (admin-granted, heavily sandboxed).

---

## 🏛 Architecture

**A modular monolith, organized as vertical slices, with Clean/Hexagonal boundaries
inside each module.** One FastAPI process + one PostgreSQL database + one React SPA —
but the code is partitioned into ten business modules that each own their tables (all
39 have exactly one writer), expose a small `public.py` contract, and receive every
cross-module capability by injection from a single composition root. Eight named
workflows coordinate cross-module writes: seven use an opaque unit-of-work for one DB
transaction; initial AI scheduling uses guarded compensation by explicit ADR. Boundaries are
**mechanically enforced** (`tools/check_architecture.py` + architecture tests), and the
external surface (routes/CLI/schema/job states) is **contract-frozen** as snapshots.

```
novelwiki/
├── modules/       identity · catalog · reading · acquisition · translation
│                  codex · narration · work · ai_execution · experience
│                  (each: public.py + domain/ + application/ + adapters/{inbound,outbound})
├── platform/      settings · db pool/UoW · web factory (CSRF/CSP) · audit · arch checks
├── kernel/        shared errors + opaque transaction contracts
├── workflows/     8 named cross-module coordinators (7 transactional + 1 compensating)
├── bootstrap/     THE composition root: wiring, lifecycle, workers, CLI
├── frontend/      React SPA (vertical slices mirroring the backend)
└── api/ auth/ db/ jobs/ …   stable compatibility aliases for external consumers
```

Start here: [docs/architecture/overview.md](docs/architecture/overview.md) · module
deep-dives: [docs/modules/](docs/modules/README.md) · decision records + migration
evidence: [docs/architecture/](docs/README.md#architecture).

```
   webnovel site ─► Scraper (adapter per site) ─┐
   EPUB / PDF ────► Importer (parse · OCR · ────┤─► chapters (global numbering)
                    segment · review · commit)   │
        ┌───────────────┬────────────────┬──────┴─────────┬──────────────────┐
        ▼               ▼                ▼                ▼                  ▼
     READER        TRANSLATION       AUDIOBOOK       CODEX (opt-in)     MULTI-USER
   progress ·    on-demand+prefetch  durable TTS →   chunk → embed →   accounts · quotas
   overlays ·    glossary ·          GPU sidecar →   forward-only      private/public/global
   bookmarks     contribute-back     cached Opus     extraction        overlays + reviews
                                                          │
                                              ┌───────────┴───────────┐
                                              │    RETRIEVAL LAYER    │
                                              │ BM25 ⊕ dense → RRF →  │
                                              │ rerank ·  ≤ ceiling   │
                                              └───────────┬───────────┘
                                                 AGENTIC ORCHESTRATOR
                                              (Pro plans · Flash distills)
   FastAPI ──► React SPA (Home · Library · Discover · Reader · Codex · Admin) ◄── cookie auth
   Optional GPU sidecars:  OCR :8077 (PaddleOCR) · TTS :8078 (OmniVoice)
```

## 🧰 Tech stack

**Backend** Python 3.12+, FastAPI + Uvicorn, asyncpg (no ORM), Typer ·
**DB** PostgreSQL + pgvector (HNSW) + pg_trgm ·
**Auth** server-side sessions, argon2-cffi, hand-rolled OAuth (httpx), aiosmtplib ·
**Retrieval** bm25s ⊕ pgvector → RRF → reranker ·
**LLM** OpenRouter ("Flash reads, Pro thinks"), Gemini vision for OCR escalation;
optional AGY CLI backend ·
**Scraping** curl-cffi + selectolax/lxml, json-repair ·
**Import** ebooklib, pymupdf, nh3, pillow, ftfy ·
**TTS** OmniVoice sidecar, ffmpeg → Opus ·
**Frontend** React 18 + TanStack Query, Vite 6, served same-origin by FastAPI ·
**Packaging** uv (`pyproject.toml` + `uv.lock`)

---

## 🚀 Getting started

Full guide: [docs/getting-started/local-setup.md](docs/getting-started/local-setup.md).

```bash
uv sync
cp .env.example .env    # set DATABASE_URL, DB_SUPERUSER_URL, OPENROUTER_API_KEY,
                        # SESSION_SECRET, ADMIN_EMAIL/ADMIN_PASSWORD; COOKIE_SECURE=false for dev
cd novelwiki/frontend && npm ci && npm run build && cd ../..
uvicorn novelwiki.api.app:app --reload --port 8000     # or: python main.py
```

Schema is **auto-created** on startup (the app creates the DB via `DB_SUPERUSER_URL` if
missing, then applies idempotent DDL; explicitly: `python -m novelwiki.db.schema`). The
first boot bootstraps the admin and — on a legacy single-user DB — runs a guarded
multi-user migration (**pg_dump first**; see the setup guide). Every setting is
documented in [docs/operations/configuration.md](docs/operations/configuration.md).

### CLI

```bash
python -m novelwiki.cli --help
# add-novel · scrape · chunk · embed · extract · translate · import · import-batch
# · import-series · import-worker · rebuild-bm25 · merge · reset-db
```

Reference + recipes: [docs/api/cli.md](docs/api/cli.md). The HTTP API (119 routes):
[docs/api/http-api.md](docs/api/http-api.md), or `/docs` on a running instance.

---

## 🧪 Testing & gates

```bash
uv run python tools/check_architecture.py    # boundary rules (no DB)
uv run pytest -q tests                       # unit + architecture + contract snapshots (no DB)
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/novelwiki \
TEST_DB_SUPERUSER_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  uv run python scripts/test_backend.py      # creates/drops a random tg_pytest_* DB
cd novelwiki/frontend && npm test && npm run build && npm run test:e2e
```

The suites never touch your real database. Contract snapshots freeze routes/OpenAPI/
CLI/schema/job-states — intentional changes regenerate them via
`uv run python scripts/contracts.py --update`.
Details: [docs/testing.md](docs/testing.md) ·
[docs/architecture/enforcement.md](docs/architecture/enforcement.md).

---

## 🐳 Docker & deployment

```bash
docker compose up -d --build     # web app on 127.0.0.1:8001 (front it with a tunnel/proxy)
docker compose up -d ocr         # + OCR sidecar (GPU; scanned PDFs)
docker compose up -d tts         # + TTS sidecar (GPU; audiobooks)
```

Source is **baked into the image** (deploy = rebuild); only `/app/data` persists.
Sidecars sit on a private bridge with **unpublished ports** and require a shared service
token (`SIDECAR_AUTH_TOKEN`) — they fail closed without it; both are optional and the
app degrades gracefully. Host PostgreSQL is reached via `host.docker.internal`. The
optional AGY worker runs on the host under systemd
([docs/agy-operator-runbook.md](docs/agy-operator-runbook.md)).
Full topology + first boot + release/rollback:
[docs/operations/deployment.md](docs/operations/deployment.md) ·
[docs/release-runbook.md](docs/release-runbook.md).

---

## 📖 Documentation map

| | |
|---|---|
| **Start** | [docs/README.md](docs/README.md) (hub with reading paths) |
| Product & setup | [what-is-tideglass](docs/getting-started/what-is-tideglass.md) · [local-setup](docs/getting-started/local-setup.md) · [repo-tour](docs/getting-started/repo-tour.md) |
| Concepts | [primer](docs/concepts/primer.md) · [spoiler-safety](docs/concepts/spoiler-safety.md) · [glossary](docs/concepts/glossary.md) |
| Architecture | [overview](docs/architecture/overview.md) · [module-anatomy](docs/architecture/module-anatomy.md) · [composition-root](docs/architecture/composition-root.md) · [workflows](docs/architecture/workflows-and-transactions.md) · [platform](docs/architecture/platform.md) · [enforcement](docs/architecture/enforcement.md) |
| Modules | [map](docs/modules/README.md) + one doc per module |
| Pipelines | [jobs & quota](docs/pipelines/background-jobs-and-quota.md) · [scraping](docs/pipelines/scraping.md) · [import](docs/pipelines/file-import.md) · [translation](docs/pipelines/translation.md) · [codex](docs/pipelines/codex-build-and-ask.md) · [narration](docs/pipelines/narration.md) · [AI backends](docs/pipelines/ai-backends.md) |
| Reference | [DB schema](docs/data/database-schema.md) · [filesystem](docs/data/filesystem-layout.md) · [HTTP behavior](docs/api/http-api.md) · [exact route inventory](docs/api/http-route-inventory.md) · [CLI](docs/api/cli.md) · [configuration](docs/operations/configuration.md) |
| Operating | [deployment](docs/operations/deployment.md) · [security](docs/operations/security.md) · [testing](docs/testing.md) · [release runbook](docs/release-runbook.md) · [AGY runbook](docs/agy-operator-runbook.md) |
| Frontend | [overview](docs/frontend/overview.md) |
