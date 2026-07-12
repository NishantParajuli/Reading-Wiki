# Deployment

> How Tideglass runs in production: one web container, an optional GPU sidecar pair, a
> host PostgreSQL, and (optionally) a dedicated AGY host worker. Release/rollback
> procedure: [../release-runbook.md](../release-runbook.md). Configuration:
> [configuration.md](configuration.md).

## Topology

```
 Internet ──▶ Cloudflare tunnel (host) ──▶ 127.0.0.1:8001 ──▶ web container (uvicorn :8001)
                                                             │  FastAPI + SPA + 3 workers
                                                             ├──▶ host PostgreSQL via
                                                             │    host.docker.internal:5432
                                                             ├──▶ ocr:8077   (private bridge)
                                                             └──▶ tts:8078   (private bridge)
 host systemd (--user) ──▶ novelwiki-agy-worker (python -m novelwiki.agy.worker) ─▶ same DB
```

Key properties:

- **Source is baked into the image** — deploying a change means `docker compose build web
  && docker compose up -d web`. There is no bind-mounted code.
- The web port binds **loopback only** (`127.0.0.1:8001`); the tunnel fronts it. Sidecar
  ports are **never published to the host** — only the web service reaches them over the
  private bridge `novelwiki_net`, so tunnel/Access rules can't be bypassed.
- Persistent state: PostgreSQL (host) + the named volume `novelwiki_data` mounted at
  `/app/data` (BM25 indexes, assets, audio, import artifacts — see
  [../data/filesystem-layout.md](../data/filesystem-layout.md)).

## The web image (`Dockerfile`, three stages)

1. `node:20-slim` — `npm ci && npm run build` → the SPA bundle.
2. `uv` builder (`python3.12-bookworm-slim`) — `uv sync --frozen` from `uv.lock` into
   `/app/.venv`, bytecode-compiled.
3. Runtime `python:3.12-slim-bookworm` — venv + `novelwiki/` + `main.py` copied in, the
   compiled SPA placed at `novelwiki/frontend/dist`, **non-root user `app` (uid 10001)**,
   `CMD uvicorn novelwiki.api.app:app` on `:8001`.

## docker-compose services

| Service | Port | Profile | Notes |
|---|---|---|---|
| `web` | `127.0.0.1:8001` | default | `.env` + overrides: `OCR_SIDECAR_URL=http://ocr:8077`, `TTS_SIDECAR_URL=http://tts:8078`; `extra_hosts: host.docker.internal:host-gateway` for the host DB; volume `wiki_data:/app/data`; `restart: unless-stopped` |
| `ocr` | 8077 (bridge-only) | `ocr` | PaddleOCR PP-StructureV3, NVIDIA GPU reservation; optional — digital PDFs/EPUBs don't need it and scanned pages can fall back to Gemini |
| `tts` | 8078 (bridge-only) | `tts` | OmniVoice, NVIDIA GPU reservation; HF cache volume so the model isn't re-downloaded; `voices/` and `tts_server.py` bind-mounted read-only (clip/code tweaks = restart, no CUDA rebuild) |

Both sidecars require the shared token (`SIDECAR_AUTH_TOKEN` → header
`X-Tideglass-Sidecar-Token`) and **fail closed** without it unless
`SIDECAR_ALLOW_UNAUTHENTICATED=1` is set explicitly for local dev. On a single small GPU
(~6 GB), run one heavy sidecar at a time.

```bash
docker compose up -d web            # the app
docker compose up -d ocr            # + scanned-PDF OCR (GPU)
docker compose up -d tts            # + narration (GPU)
```

`DATABASE_URL`/`DB_SUPERUSER_URL` in `.env` must point at
`host.docker.internal:5432` (the compose file maps it to the host gateway).

## First boot

Startup order (the lifecycle,
[../architecture/composition-root.md §3](../architecture/composition-root.md)): schema
ensure (creates the database via `DB_SUPERUSER_URL` if missing, applies idempotent DDL) →
pool → identity cleanup → the guarded multi-user migration (bootstraps the first admin
from `ADMIN_EMAIL`/`ADMIN_PASSWORD`; **rewrites legacy single-user data — pg_dump first**
and confirm via `MULTIUSER_MIGRATION_BACKUP_CONFIRMED` or run
`python -m novelwiki.db.migrate_multiuser` supervised) → the three workers → AGY health
check. Then: `curl localhost:8001/health`, log in, done.

## The AGY host worker (optional)

Runs on the **host**, not in Docker — it needs the operator's authenticated `agy` CLI
keyring session. Install `deploy/novelwiki-agy-worker.service` as a `systemd --user`
unit (`loginctl enable-linger` if it must survive logout) and follow
[../agy-operator-runbook.md](../agy-operator-runbook.md) step by step (binary hash pin,
model catalog check, plugin validation, permission-rule verification, explicit per-user
grants). Kill switch: `AGY_ENABLED=false` + restart consumers.

## Deploying a change

```bash
git pull
docker compose build web
docker compose up -d web       # workers stop gracefully; leases/durable jobs resume
```

Durable jobs survive this by design: queued work stays queued; running generic/import
work is reclaimed after lease expiry, while the single-instance TTS worker requeues
interrupted `generating` jobs at startup and skips audio already cached. For
release-candidate rigor (contract gates, backup rehearsal, image-digest rollback), follow
[../release-runbook.md](../release-runbook.md).

## Running without Docker (dev)

```bash
uv sync
cp .env.example .env           # fill in; COOKIE_SECURE=false for plain-HTTP localhost
(cd novelwiki/frontend && npm ci && npm run build)   # or `npm run dev` for HMR
uvicorn novelwiki.api.app:app --reload --port 8000   # or: python main.py
```

Sidecars are optional in dev; without them, scanned-PDF OCR and narration are the only
features that degrade.
