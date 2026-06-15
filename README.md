# 📖 Tideglass — a self-hosted webnovel reading platform

A single-user, self-hosted platform for reading webnovels end to end: **scrape → read → translate → (optionally) build a spoiler-safe codex.** Point it at a chapter URL, let it crawl, and read in a cozy, distraction-free reader. Raw (foreign-language) chapters are translated on demand as you open them, and any novel can opt into an agentic, **spoiler-gated** knowledge base.

The codex upholds **THE ONE INVARIANT**:

> When you are reading at **chapter N**, no information from any chapter **> N** may ever appear in a codex entry, a stat, or a Q&A answer.

That boundary is enforced at the **database and retrieval layers** (`WHERE chapter <= ceiling` on every read) — never by trusting the LLM to hold back.

---

## ✨ What it does

- **Library** — Track every novel you're reading on shelves (`to_read` / `reading` / `completed`) with status tags, covers, and reading progress.
- **Multi-source scraping** — A novel can be stitched from several sources (e.g. an English site that ends at ch. 124 + a raw site that continues at 125). Each source carries a `chapter_offset` that maps its local numbering onto one continuous **global** chapter sequence. Scraping is incremental and stops cleanly when it hits premium/paywalled chapters.
- **Reader** — Immersive tap-to-toggle UI, adjustable width, themes, configurable auto-scroll, and persistent scroll-position recovery. Prev/next spans all sources by global chapter number. Reading progress and bookmarks are saved per novel.
- **On-demand translation** — Opening a raw chapter translates it inline (and prefetches the next few in the background) so reading flows without waiting at each boundary. A per-novel **glossary** keeps names/terms consistent across chapters and across a source switch (e.g. `林轩 → Lin Xuan` once, everywhere after).
- **Spoiler-safe codex** *(opt-in per novel)* — Chunk → embed → forward-only entity/fact/relationship extraction → hybrid retrieval → agentic Q&A, all bounded to your current chapter. Browse entities, read synthesized profiles, follow relationships and timelines, see identity-reveal banners only once the reveal chapter is within your ceiling, and ask freeform questions with inline citations.

---

## 🏛 Architecture overview

```
   webnovel site ──► Scraper (adapter per site) ──► chapters (global numbering, content / original_text)
                                                          │
                          ┌───────────────────────────────┼───────────────────────────────┐
                          ▼                                ▼                                 ▼
                       READER                       TRANSLATION                      CODEX (opt-in)
              progress · bookmarks ·       on-demand on open + prefetch ·    chunk → embed → forward-only
              scroll recovery · TOC        per-novel glossary (name           extraction (entities/facts/
              across all sources           consistency, cross-source)         relations/events/identities)
                                                                                       │
                                                              ┌────────────────────────┴───────────────────────┐
                                                              │                  RETRIEVAL LAYER                 │
                                                              │  BM25 (bm25s) ⊕ dense (pgvector) → RRF → rerank  │
                                                              │  + structured tools (facts / graph / timeline)  │
                                                              │  ── every read bounded by WHERE chapter <= N ──  │
                                                              └────────────────────────┬─────────────────────────┘
                                                                                       │
                                                                          AGENTIC ORCHESTRATOR
                                                                  Pro plans → Flash retrieves & distills →
                                                                  Pro reasons → Flash verifies (loop, capped)
                                                                                       │
                                              FastAPI  ──►  React UI (Library · Reader · Codex)
```

---

## 🧰 Tech stack

- **Backend:** Python 3.12+, FastAPI + Uvicorn, `asyncpg`
- **Database:** PostgreSQL with `pgvector` (dense vectors / HNSW) and `pg_trgm` (fuzzy name matching)
- **Retrieval:** `bm25s` (sparse/lexical) ⊕ pgvector (dense) → Reciprocal Rank Fusion → reranker
- **LLM:** [OpenRouter](https://openrouter.ai) — a "Flash reads, Pro thinks" split for extraction/Q&A, plus a translation model. Embeddings and reranking are configurable model IDs.
- **Scraping:** `curl-cffi` (TLS-fingerprint-resistant fetch) + `selectolax` / `lxml` parsing, `json-repair` for robust LLM/JSON handling
- **Frontend:** React 18 (production UMD builds) with in-browser Babel JSX — **no build step**, served as static files by FastAPI
- **Packaging:** `uv` (with `pyproject.toml` + `uv.lock`)

---

## 🚀 Getting started

### 1. Prerequisites
- **Python 3.12+** (and [`uv`](https://github.com/astral-sh/uv), recommended)
- **PostgreSQL** with the `vector` and `pg_trgm` extensions available
- An **OpenRouter API key** (for translation, extraction, embeddings, reranking, and Q&A)

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

Then fill in `.env`. Key settings (see [novelwiki/config/settings.py](novelwiki/config/settings.py) for the full list and defaults):

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | App DB connection (plain `postgresql://` — **not** the SQLAlchemy dialect form) |
| `DB_SUPERUSER_URL` | Superuser connection used to auto-create the DB on first run |
| `OPENROUTER_API_KEY` | Unified key for chat, translation, embeddings, and rerank calls |
| `MODEL_PRO` / `MODEL_FLASH` | Planner/reasoner vs. cheap reader/distiller (may be the same model) |
| `MODEL_TRANSLATE` | Model used to translate raw chapters |
| `EMBED_MODEL` / `EMBED_DIM` | Embedding model and its vector dimension |
| `RERANK_MODEL` | Reranker model |

> **Schema is auto-created.** On server startup (and CLI use) the app connects with `DB_SUPERUSER_URL`, creates the `novelwiki` database if missing, then applies idempotent DDL. You can also run it explicitly:
>
> ```bash
> python -m novelwiki.db.schema
> ```

---

## 🌐 Running the server

```bash
uvicorn novelwiki.api.app:app --reload --host 0.0.0.0 --port 8000
# or simply:
python main.py            # serves on :8000
```

Open **http://localhost:8000** — the React UI is served directly by FastAPI (no separate frontend build/server). The browser only ever talks to the chapter-bounded API, so nothing past your ceiling reaches it.

**UI surfaces:**
1. **Library** — your shelves of novels with progress and quick actions.
2. **Novel detail** — manage sources (add/edit, set `chapter_offset`), trigger scraping, manage the translation glossary, and build/rebuild the codex.
3. **Reader** — the immersive reading view (themes, width, auto-scroll, bookmarks, scroll recovery).
4. **Codex** *(if enabled)* — a chapter-ceiling slider plus Home stats, Browse/search entities, Entity pages (synthesized profile + facts + relationships + timeline + identity-reveal banners), and **Ask** (agentic Q&A with inline, popover-backed citations).

---

## 🛠 Command-line interface

The CLI drives the full ingestion pipeline. Invoke it as a module from the repo root:

```bash
python -m novelwiki.cli --help
```

```bash
# 1. Create a novel + its first source (prints the new ids)
python -m novelwiki.cli add-novel "Example Novel" "https://fenrirealm.com/novel/example/chapter-1" --adapter fenrirealm

# 2. Scrape (all sources of a novel, or one with --source); stops cleanly at premium
python -m novelwiki.cli scrape <novel_id> --max 50

# 3. Translate raw chapters (on-demand glossary-consistent); --seed pulls names from the codex
python -m novelwiki.cli translate <novel_id> --from 1 --to 50

# ── Codex pipeline (only for codex-enabled novels) ──
python -m novelwiki.cli chunk <novel_id>          # paragraph-aware chunking
python -m novelwiki.cli embed <novel_id>          # batch vector embeddings
python -m novelwiki.cli extract <novel_id>        # forward-only metadata extraction
python -m novelwiki.cli rebuild-bm25 <novel_id>   # build/refresh the per-novel BM25 index

# Merge two duplicate entities
python -m novelwiki.cli merge <novel_id> --keep <id> --drop <id>

# Drop ALL tables and re-apply schema (destructive)
python -m novelwiki.cli reset-db
```

> The UI's codex "Build" button runs `chunk → embed → extract → rebuild-bm25` for you in the background; the CLI exposes each step individually.

---

## 🔌 Scraper adapters

Each source picks an adapter by key. Built-in adapters live in [novelwiki/scraper/adapters.py](novelwiki/scraper/adapters.py):

`fenrirealm` · `readhive` · `boti-translations` · `69shuba`

Add a new site by subclassing `BaseAdapter` (or `_PagedHtmlAdapter`) and registering it in the `ADAPTERS` dict — it then appears automatically in the Add-Source dropdown via `list_adapters()`.

---

## 🗄 Data model

Everything is **novel-scoped** (single shared Postgres DB, `novel_id` on every table — no schema-per-novel). Schema is defined in [novelwiki/db/schema.py](novelwiki/db/schema.py):

- **Reading:** `novels`, `sources`, `chapters` (PK `(novel_id, number)`; `content` = readable text, `original_text` = source language for re-translation without re-scrape), `reading_progress`, `bookmarks`
- **Translation:** `translation_glossary` (per-novel name/term anchors; `locked` rows are user-pinned)
- **Codex:** `chunks` (+`embedding`), `entities`, `entity_descriptions`, `entity_aliases`, `identity_links`, `entity_facts`, `relationships`, `events`, `extraction_state` (running story-so-far), `wiki_cache` (synthesized profiles), `query_cache`

---

## 🧪 Testing

Spoiler boundaries, cache invalidation, and pipeline tasks are verified with `pytest`:

```bash
uv run pytest                 # runs novelwiki/eval/*_tests.py (see pyproject.toml)
# or target the suites directly:
uv run pytest novelwiki/eval/spoiler_tests.py novelwiki/eval/pipeline_tests.py
```

---

## 🐳 Docker

A multi-stage [Dockerfile](Dockerfile) builds a `uv`-synced runtime image (non-root, serves on **:8001**). The source and frontend are **baked into the image at build time** — only `/app/data` (BM25 indexes + scrape cache) is a persistent volume, so deploying changes means rebuilding the image.

```bash
docker compose up -d --build
```

`docker-compose.yml` uses `network_mode: host` so the container can reach a PostgreSQL running on the host's `localhost`, and reads configuration from `.env`.
