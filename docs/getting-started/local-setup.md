# Local setup

From zero to a running instance with one novel in it. (Production deployment is
[../operations/deployment.md](../operations/deployment.md); full config reference is
[../operations/configuration.md](../operations/configuration.md).)

## 1. Prerequisites

- **Python 3.12+** and [`uv`](https://github.com/astral-sh/uv) (recommended; plain pip
  works too)
- **PostgreSQL** with the `vector` (pgvector) and `pg_trgm` extensions available
- **Node 20+** (to build the frontend)
- An **OpenRouter API key** — always used for embeddings and reranking, and used for
  generation when native DeepSeek is not configured
- Optional: a **DeepSeek API key** — routes the default V4 Flash/Pro translation,
  extraction, segmentation, and Q&A models directly to DeepSeek
- Optional: a **Gemini API key** (scanned-PDF OCR escalation), an **NVIDIA GPU**
  (OCR/TTS sidecars), Docker

## 2. Install

```bash
git clone <repo> wiki && cd wiki
uv sync                      # creates .venv from uv.lock
# — or —
python -m venv .venv && source .venv/bin/activate && pip install -e .
```

## 3. Configure

```bash
cp .env.example .env
```

Minimum edits for dev:

```dotenv
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/novelwiki
DB_SUPERUSER_URL=postgresql://postgres:postgres@localhost:5432/postgres
OPENROUTER_API_KEY=sk-or-...
DEEPSEEK_API_KEY=sk-...                # optional native V4 generation
SESSION_SECRET=any-long-random-string
COOKIE_SECURE=false                  # plain-HTTP localhost
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=choose-one            # first admin, created on first boot
# SMTP_HOST left blank ⇒ verification/reset links are logged, not emailed (dev mode)
```

You do **not** create the database or run migrations by hand: on startup the app
connects with `DB_SUPERUSER_URL`, creates the `novelwiki` DB if missing, and applies the
idempotent schema (explicitly: `python -m novelwiki.db.schema`).

## 4. Build the frontend, run the server

```bash
cd novelwiki/frontend && npm ci && npm run build && cd ../..
uvicorn novelwiki.api.app:app --reload --host 0.0.0.0 --port 8000
# or: python main.py
```

Open http://localhost:8000 — register, or log in with the bootstrapped admin. The SPA is
served by FastAPI itself; there is no separate frontend server. For frontend work, Vite
defaults its proxy to backend port 8001. With the port-8000 command above, run
`VITE_API_PROXY=http://localhost:8000 npm run dev` instead of rebuilding.

Startup also launches the three background workers (import, TTS, generic jobs) inside
the server process — no extra processes needed in dev.

## 5. Add your first novel

**Via UI:** Library → Add novel → paste a chapter-1 URL and pick an adapter, or drop an
EPUB on the Import screen.

**Via CLI:**

```bash
python -m novelwiki.cli add-novel "Example Novel" \
  "https://fenrirealm.com/novel/example/chapter-1" --adapter fenrirealm
python -m novelwiki.cli scrape 1 --max 25
```

Then (optionally) build the codex from the novel's Manage tab, or:

```bash
python -m novelwiki.cli chunk 1 && python -m novelwiki.cli embed 1 && \
python -m novelwiki.cli extract 1 && python -m novelwiki.cli rebuild-bm25 1
```

All 14 commands: [../api/cli.md](../api/cli.md).

## 6. Run the tests

```bash
uv run python tools/check_architecture.py   # boundary rules (no DB needed)
uv run pytest -q tests                      # unit + architecture + contracts (no DB)
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/novelwiki \
TEST_DB_SUPERUSER_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  uv run python scripts/test_backend.py     # creates/drops a random tg_pytest_* DB
cd novelwiki/frontend && npm test
```

Details: [../testing.md](../testing.md).

## 7. Optional extras

- **Sidecars** (GPU): `docker compose up -d ocr` / `docker compose up -d tts`; set
  `SIDECAR_AUTH_TOKEN`. Without them: scanned-PDF OCR falls back to Gemini-only or
  waits; narration jobs fail politely with "sidecar unavailable".
- **OAuth buttons**: set `GOOGLE_*` / `DISCORD_*` client credentials; redirect URI is
  `{PUBLIC_BASE_URL}/api/auth/oauth/{provider}/callback`.
- **AGY backend**: deliberately involved to enable — follow
  [../agy-operator-runbook.md](../agy-operator-runbook.md).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Could not check/create database` warning | `DB_SUPERUSER_URL` wrong — create the DB manually and it proceeds |
| 403 "CSRF token missing" from curl | send `x-tideglass-csrf` matching the `tg_csrf` cookie (or `x-tideglass-request: 1` on auth routes) — see [../api/http-api.md](../api/http-api.md) |
| Login cookie not set on localhost | `COOKIE_SECURE=true` on plain HTTP — set `false` in dev |
| Frontend 404s / blank page | `novelwiki/frontend/dist` missing — run `npm run build` |
| `vector` extension error at startup | install pgvector for your PostgreSQL version |
| Verification email "not arriving" | no `SMTP_HOST` in dev — the link is in the server log |
