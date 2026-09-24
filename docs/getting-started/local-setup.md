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
uv sync --frozen             # creates .venv from uv.lock
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
PUBLIC_BASE_URL=http://localhost:8000 # match the backend port below for email/OAuth links
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=choose-one            # first admin, created on first boot
# SMTP_HOST left blank ⇒ no mail is sent; token values are redacted in server logs
```

You do **not** create the database or run migrations by hand: on startup the app
connects with `DB_SUPERUSER_URL`, creates the `novelwiki` DB if missing, and applies the
idempotent schema (explicitly: `uv run python -m novelwiki.db.schema`).

The commands below use `uv run` to select the installed project environment; `uv sync`
does not activate it in your shell. If you chose the pip installation above, keep
`.venv` activated and omit the `uv run` prefix.

## 4. Build the frontend, run the server

```bash
cd novelwiki/frontend && npm ci && npm run build && cd ../..
uv run uvicorn novelwiki.api.app:app --reload --host 127.0.0.1 --port 8000
# or: uv run python main.py
```

Open http://localhost:8000 — register, or log in with the bootstrapped admin. The SPA is
served by FastAPI itself; there is no separate frontend server. For frontend work, Vite
defaults its proxy to backend port 8001. With the port-8000 command above, open a
second terminal and run:

```bash
cd novelwiki/frontend
VITE_API_PROXY=http://127.0.0.1:8000 npm run dev
```

Use the Vite URL (`http://localhost:5173`) for hot-reloaded frontend work. The backend
must still be running. OAuth callbacks and emailed links use `PUBLIC_BASE_URL`.

The bootstrapped admin is already email-verified. To exercise registration verification
or password reset, configure SMTP; a local mail-capture service can receive development
mail (`SMTP_HOST`, `SMTP_PORT`, and `SMTP_STARTTLS=false` when that local service has no
TLS). Leaving SMTP blank records the attempted mail, but the shared logger redacts the
token in its link, so the log is not a usable verification/reset inbox.

Startup also launches the three background workers (import, TTS, generic jobs) inside
the server process — no extra processes needed in dev.

## 5. Add your first novel

**Via UI:** Library → Add novel → choose a website and paste its supported novel or
chapter URL, or drop an EPUB on the Import screen. The website choice sets language and
raw-translation defaults; check them before saving. Raw FuckNovelpia also asks for the
downloaded archive's ZIP password. The [supported-sites guide](../pipelines/supported-sites.md)
lists URL formats and source-specific limits.

**Via CLI:**

```bash
uv run python -m novelwiki.cli add-novel "Example Novel" \
  "https://fenrirealm.com/series/example/1" --adapter fenrirealm
uv run python -m novelwiki.cli scrape NOVEL_ID --max 25
```

Replace the example URL with a real chapter URL and `NOVEL_ID` with the ID printed by `add-novel`. CLI-created novels are
system-owned; use an admin account to manage them. To create a novel owned by your
reader account, use the UI. Then (optionally) build the codex from Manage, or:

```bash
uv run python -m novelwiki.cli chunk NOVEL_ID
uv run python -m novelwiki.cli embed NOVEL_ID
uv run python -m novelwiki.cli extract NOVEL_ID
uv run python -m novelwiki.cli rebuild-bm25 NOVEL_ID
```

All 14 commands: [../api/cli.md](../api/cli.md).

## 6. Run the tests

```bash
uv run python tools/check_architecture.py --strict  # all boundary/layer rules (no DB needed)
uv run pytest -q tests                      # unit + architecture + contracts (no DB)
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/novelwiki \
TEST_DB_SUPERUSER_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  uv run python scripts/test_backend.py     # creates/drops a random tg_pytest_* DB
cd novelwiki/frontend && npm test
```

Details: [../testing.md](../testing.md).

## 7. Optional extras

- **Sidecars** (GPU): `docker compose up -d ocr` / `docker compose up -d tts`; set
  `SIDECAR_AUTH_TOKEN`. Without them: scanned-PDF OCR falls back to Gemini when it is
  configured; otherwise the import fails with `No OCR backend available` and must be
  resubmitted after an OCR backend is available. Narration jobs fail politely with
  "sidecar unavailable".
- **OAuth buttons**: set `GOOGLE_*` / `DISCORD_*` client credentials; redirect URI is
  `{PUBLIC_BASE_URL}/api/auth/oauth/{provider}/callback`.
- **AGY backend**: deliberately involved to enable — follow
  [../agy-operator-runbook.md](../agy-operator-runbook.md).
- **OpenAI Codex backend**: also an explicit operator rollout — follow
  [../openai-codex-operator-runbook.md](../openai-codex-operator-runbook.md).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Could not check/create database` warning | `DB_SUPERUSER_URL` wrong — create the DB manually and it proceeds |
| 403 "CSRF token missing" from curl | send `x-tideglass-csrf` matching the `tg_csrf` cookie (or `x-tideglass-request: 1` on auth routes) — see [../api/http-api.md](../api/http-api.md) |
| Login cookie not set on localhost | `COOKIE_SECURE=true` on plain HTTP — set `false` in dev |
| Frontend 404s / blank page | `novelwiki/frontend/dist` missing — run `npm run build` |
| `vector` extension error at startup | install pgvector for your PostgreSQL version |
| Verification email "not arriving" | configure SMTP or a local mail-capture service; blank `SMTP_HOST` sends nothing and logged tokens are redacted |
