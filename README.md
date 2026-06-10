# 📖 Spoiler-Aware Webnovel Wiki

A state-of-the-art **spoiler-gated knowledge base and agentic Q&A wiki** designed specifically for reading webnovels sequentially. 

As a reader, you are at **Chapter N**. This wiki guarantees **THE ONE INVARIANT**:
> **No information from any chapter > N may ever appear in an answer or a lore profile when the user is at chapter N.**

This boundary is strictly enforced at the **database and data-retrieval layers**, never relying on LLM caution alone.

---

## 🏛 Architecture Overview

```
                         ┌──────────────┐
   webnovel site ──────► │   Scraper    │ ──► chapters (raw_html, clean_text)
                         └──────────────┘
                                │
              ┌─────────────────┼──────────────────────────────┐
              ▼                                                 ▼
      ┌──────────────┐                                 ┌─────────────────┐
      │  Chunk+Embed │ ──► chunks(+embedding)           │ Forward-only    │
      └──────────────┘                                 │ Extraction (Flash)
                                                        └─────────────────┘
                                                                │
                                          entities / aliases / identity_links /
                                          facts / relationships / events / extraction_state
              ┌──────────────────────────────────────────────────────────────┐
              │                       RETRIEVAL LAYER                          │
              │  hybrid_search = BM25(bm25s) ⊕ dense(pgvector)  →  RRF  →       │
              │  Cohere rerank   +   structured tools (facts/graph/timeline)   │
              │  ── every read bounded by WHERE chapter <= ceiling ──          │
              └──────────────────────────────────────────────────────────────┘
                                          │
                         ┌────────────────┴─────────────────┐
                         │     AGENTIC ORCHESTRATOR          │
                         │  Pro plans → (Flash retrieves &   │
                         │  distills) → Pro reasons → Flash  │
                         │  verifies → answer    (loop, cap) │
                         └───────────────────────────────────┘
                                          │
                                  FastAPI  ──►  Tideglass Codex UI
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.12+**
- **PostgreSQL 18** with `pgvector` and `pg_trgm` extensions enabled.
- **Docker & Docker Compose** (optional, recommended for fast DB spinning)

### 2. Install Dependencies
This project uses modern Python packaging via `uv` or `pip`:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Configuration
Create a `.env` file from the provided example:
```bash
cp .env.example .env
```
Fill in your API keys:
- `OPENROUTER_API_KEY`: For chat, embeddings, and reranker calls.

### 4. Initialize Schema & Database
Generate tables, setup pgvector HNSW indexes, and verify connections:
```bash
python -m novelwiki.db.schema
```

---

## 🛠 Command-Line Interface (CLI)

Manage the entire ingestion pipeline end-to-end via CLI:

```bash
# 1. Scrape chapters sequentially
python novelwiki/cli.py scrape "https://fenrirealm.com/novel/example-novel/chapter-1" --max 50

# 2. Chunk chapter bodies on paragraph boundaries
python novelwiki/cli.py chunk

# 3. Generate batch vector embeddings
python novelwiki/cli.py embed

# 4. Chronological forward-only metadata extraction
python novelwiki/cli.py extract

# 5. Build/refresh the BM25 index
python novelwiki/cli.py rebuild-bm25
```

---

## 🧪 Testing

We verify all non-negotiable constraints, spoiler boundaries, cache invalidations, and pipeline tasks using `pytest`:

```bash
PYTHONPATH=. ./.venv/bin/pytest novelwiki/eval/spoiler_tests.py novelwiki/eval/pipeline_tests.py
```

---

## 🌐 FastAPI Server & Premium UI

Start the backend application server:
```bash
uvicorn novelwiki.api.app:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` in your web browser. The UI is the **Tideglass Codex** — a
cozy, spoiler-safe reading companion (React + Babel-in-browser, served as static files; no
build step). It talks only to the chapter-bounded API, so nothing past your ceiling ever
reaches the browser.

1. **Chapter-ceiling bar**: A first-class slider pinned under the header. Everything —
   home stats, the codex, entity pages, and answers — re-bounds live as you move it.
   Entities you newly unlock animate in; what's still ahead shows only a decorative,
   data-free "Not yet revealed" teaser (the boundary is never crossed to render it).
2. **Home**: Hero + spoiler-safe aggregate stats (entities revealed, facts known,
   relationships mapped, % read — all `WHERE … <= ceiling`).
3. **Codex (browse)**: Search + type filters over entities visible at your ceiling.
4. **Entity pages**: The synthesized codex entry (`wiki_cache`), what's-known facts,
   relationships, a chronological timeline, and **identity-reveal banners** that fold
   personas together only once the reveal chapter is within your ceiling.
5. **Ask**: Freeform Q&A. The four-step agent animation (Pro plans → Flash retrieves &
   distills → Pro reasons → Flash verifies) mirrors the real orchestrator, and the answer
   renders with clickable, popover-backed inline citations.
6. **Admin** (gear icon, top-right): Gated ingestion controls — scrape, chunk, embed,
   extract, rebuild-BM25, and merge-entities — wrapping the `/api/admin/*` endpoints.
   These trigger real scraping and paid API calls, so they live off the primary nav.
