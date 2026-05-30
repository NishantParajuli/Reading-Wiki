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
                                  FastAPI  ──►  Premium Glassmorphic UI
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.12+**
- **PostgreSQL 18** with `pgvector` and `pg_trgm` extensions enabled.
- **Docker & Docker Compose** (optional, recommended for fast DB spinning)

### 2. Database Spinup
Run the pre-configured Postgres container using Docker Compose:
```bash
docker compose up -d
```

### 3. Install Dependencies
This project uses modern Python packaging via `uv` or `pip`:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4. Configuration
Create a `.env` file from the provided example:
```bash
cp .env.example .env
```
Fill in your API keys:
- `OPENROUTER_API_KEY`: For chat, embeddings, and reranker calls.

### 5. Initialize Schema & Database
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

Open `http://localhost:8000` in your web browser to explore:
1. **Interactive Slider**: Instantly adjust your Chapter Ceiling to filter profiles and LLM chats dynamically.
2. **Lore Chatbot**: Input freeform questions; Pro decides planning, Flash digests raw segments, and verifiers validate answers.
3. **Entity Directory**: Slide drawer profiles demonstrating combined personas, chronological timelines, and active relationship connections.
