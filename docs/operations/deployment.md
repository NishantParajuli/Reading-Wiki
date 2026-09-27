# Deployment

> How Tideglass runs in production: one web container, optional GPU and Novelpia browser
> sidecars, a host PostgreSQL, and optional dedicated AGY/OpenAI Codex host workers. Release/rollback
> procedure: [../release-runbook.md](../release-runbook.md). Configuration:
> [configuration.md](configuration.md).

## Topology

```
 Internet ──▶ Cloudflare tunnel (host) ──▶ 127.0.0.1:8001 ──▶ web container (uvicorn :8001)
                                                             │  FastAPI + SPA + 3 workers
                                                             ├──▶ host PostgreSQL via
                                                             │    host.docker.internal:5432
                                                             ├──▶ ocr:8077   (private bridge)
                                                             ├──▶ tts:8078   (private bridge)
                                                             └──▶ novelpia-browser:8079
                                                                   │ internal network
                                                                   └──▶ novelpia-egress:8899 → public HTTPS
 host systemd (--user) ──▶ AGY and/or OpenAI Codex subscription workers ─────────▶ same DB
```

Key properties:

- **Web source is baked into the image** — deploying a web change means
  `docker compose build web && docker compose up -d --no-deps web`. The web service has
  no bind-mounted code; the TTS sidecar separately mounts its server and voice clips.
- The web port binds **loopback only** (`127.0.0.1:8001`); the tunnel fronts it. Sidecar
  ports are **never published to the host**. OCR/TTS use the private bridge
  `novelwiki_net`; the optional Novelpia browser uses a separate internal network and
  controlled public HTTPS egress. Tunnel/Access rules cannot be bypassed through a
  directly published sidecar port.
- Persistent state: PostgreSQL (host) + the named volume `novelwiki_data` mounted at
  `/app/data` (BM25 indexes, assets, audio, import artifacts — see
  [../data/filesystem-layout.md](../data/filesystem-layout.md)).
- Uncached story recaps, Ask answers, and entity profiles may outlast Cloudflare's 120-second
  proxy read timeout. The SPA negotiates each endpoint's NDJSON mode, which sends an immediate
  event plus 15-second heartbeats until completion; keep streaming responses enabled through
  any replacement reverse proxy. Plain JSON API clients retain the original synchronous
  behavior and therefore remain subject to their own/proxy timeout.

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
| `novelpia-browser` | 8079 (internal network only) | `novelpia-browser` | Node/Playwright browser; fresh per-request context, authenticated RPC, no persistent profile; no GPU required |
| `novelpia-egress` | 8899 (internal network only) | `novelpia-browser` | public-only HTTPS CONNECT proxy; only this service joins the separate browser egress network |
| `tts` | 8078 (bridge-only) | `tts` | OmniVoice, NVIDIA GPU reservation; HF cache volume so the model isn't re-downloaded; `voices/` and `tts_server.py` bind-mounted read-only (clip/code tweaks = restart, no CUDA rebuild) |

The OCR and TTS sidecars require the shared token (`SIDECAR_AUTH_TOKEN` → header
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
The dedicated host-worker units set `HOST_WORKER_DATABASE_HOST=127.0.0.1`, which replaces
only the DSN hostname in those processes; credentials and the Docker-facing `.env` remain
unchanged.

## Novelpia ad browser (optional)

The `novelpia-browser` Compose profile adds a CPU browser service and its egress proxy.
It is independent of the GPU sidecars. Set a private `NOVELPIA_BROWSER_TOKEN` or the
shared `SIDECAR_AUTH_TOKEN` of at least 24 characters in the deployment environment.
Set `NOVELPIA_BROWSER_ENABLED=true` (`.env.example` starts it disabled), then build/start
the profile:

```bash
docker compose --profile novelpia-browser up -d --build novelpia-browser novelpia-egress
docker compose up -d --no-deps web
```

The web container uses `NOVELPIA_BROWSER_URL=http://novelpia-browser:8079` and enables
browser attempts when the enable variable is true (or unset in Compose). `NOVELPIA_BROWSER_ENABLED=false` disables them.
Starting ordinary `web` alone does not start this optional profile. The sidecar services
publish no host ports and persist no cookies or browser profile volumes. The browser
runs as the image's non-root user with Chromium's sandbox enabled; Compose applies
`sidecar-novelpia/seccomp_profile.json` to permit the required sandbox namespaces while
retaining syscall filtering. Keep this profile with the deployment checkout. The host
kernel must support unprivileged user namespaces; see the pinned baseline and namespace
exceptions in [SECCOMP.md](../../sidecar-novelpia/SECCOMP.md). The service still drops
all capabilities and does not use `SYS_ADMIN` or an unconfined seccomp profile. Rebuild the
browser/proxy images after changing their code; the automated web deploy does not update
these services.

The browser runs on an **internal** network shared with web and the proxy, with no direct
Internet route. The proxy alone also joins the separate `novelwiki_browser_egress_net` network; the
internal bridge is `novelwiki_browser_net`. Its CONNECT
policy permits public HTTPS destinations and rejects private/reserved addresses,
including host, metadata, and internal service addresses; the validated destination
address is pinned for the connection. This separate network boundary is necessary
because a page can contact advertising hosts and cannot use the scraper's ordinary
same-host rule. No broad scraper host override is needed.

An ad-gated scrape creates a fresh temporary browser context from the requesting user's
cookies and waits through the normal page countdown/Continue flow. The web worker's
job stage identifies the wait. Canceling closes the request and browser context.
Unavailable/busy services, expired logins, or ads that cannot complete within the deadline
fail with the chapter's manual recovery link; saved chapters stay available. Paid chapter
purchases are never automated. See the [private API](../api/novelpia-browser.md) and
[security boundary](security.md#novelpia-ad-browser).

## First boot

Startup order (the lifecycle,
[../architecture/composition-root.md §3](../architecture/composition-root.md)): schema
ensure (creates the database via `DB_SUPERUSER_URL` if missing, applies idempotent DDL) →
pool → identity cleanup → the guarded multi-user migration (bootstraps the first admin
from `ADMIN_EMAIL`/`ADMIN_PASSWORD`; **rewrites legacy single-user data — pg_dump first**
and confirm via `MULTIUSER_MIGRATION_BACKUP_CONFIRMED` or run
`python -m novelwiki.db.migrate_multiuser` supervised) → the three in-process workers → subscription-worker health
check. Then: `curl localhost:8001/health`, log in, done.

## The AGY host worker (optional)

Runs on the **host**, not in Docker — it needs the operator's authenticated `agy` CLI
keyring session. Install `deploy/novelwiki-agy-worker.service` as a `systemd --user`
unit (`loginctl enable-linger` if it must survive logout) and follow
[../agy-operator-runbook.md](../agy-operator-runbook.md) step by step (binary hash pin,
model catalog check, plugin validation, authenticated smoke/representative workload canaries,
runtime hook proof, and explicit per-user grants). Global kill switch:
`AGY_ENABLED=false`; Codex-only containment: `AGY_CODEX_ENABLED=false`. Restart settings
consumers after changing either switch.

## The OpenAI Codex host worker (optional)

This also runs on the host, separately from AGY and the web container. It needs the official
Codex CLI and a ChatGPT `codex login` session owned by the service user. Install
`deploy/novelwiki-openai-codex-worker.service` as a `systemd --user` unit and follow the
[OpenAI Codex operator runbook](../openai-codex-operator-runbook.md). Global kill switch:
`OPENAI_CODEX_ENABLED=false`; extraction-only containment:
`OPENAI_CODEX_CODEX_ENABLED=false`.

## Automated deployment after CI

Every push and pull request runs the GitHub-hosted `quality` workflow. A push to `main`
becomes deployable only after the backend, frontend, production web image, and Novelpia
browser/egress test-and-image jobs all pass.
Because this is a public repository, the production laptop is deliberately **not** a
GitHub Actions self-hosted runner. Instead, a local systemd user timer checks GitHub every
two minutes and deploys only when the latest successful `quality.yml` push SHA exactly
matches the current `main` SHA.

The deploy agent uses an isolated checkout under
`~/.local/share/tideglass-deploy/repository`, reads the existing production `.env` from
`~/wiki/.env`, builds `wiki-web:latest`, and runs:

```bash
docker compose --project-name wiki up -d --no-deps web
```

It saves the currently running image as `wiki-web:rollback` and preserves the previously
deployed commit in a separate rollback checkout. If candidate `docker compose up` fails,
or if `http://127.0.0.1:8001/health` does not become healthy, it recreates `web` from that
image using the previous release's Compose configuration. A failed SHA is not retried every
two minutes; after diagnosing the failure, remove
`~/.local/share/tideglass-deploy/failed-deployment-sha` and start
`tideglass-deploy.service` manually to retry it. The agent never recreates the OCR, TTS, or Novelpia browser/proxy
sidecars.

Install the agent once when provisioning a production laptop:

```bash
./deploy/install-tideglass-deploy-agent.sh
systemctl --user status tideglass-deploy.timer
journalctl --user -u tideglass-deploy.service -f
```

If the installer reports that user lingering is disabled, enable it so the timer runs
after reboot even before an interactive login:

```bash
sudo loginctl enable-linger "$USER"
```

Manual deployment remains available from this checkout when needed:

```bash
docker compose build --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" web
docker compose up -d --no-deps web
curl --fail http://127.0.0.1:8001/health
```

Durable jobs survive this by design: queued work stays queued; running generic/import
work is reclaimed after lease expiry, while the single-instance TTS worker requeues
interrupted `generating` jobs at startup and skips audio already cached. For
release-candidate rigor (contract gates, backup rehearsal, image-digest rollback), follow
[../release-runbook.md](../release-runbook.md).

## Running without Docker (dev)

```bash
uv sync --frozen
cp .env.example .env           # fill in; COOKIE_SECURE=false for plain-HTTP localhost
(cd novelwiki/frontend && npm ci && npm run build)   # or `npm run dev` for HMR
uv run uvicorn novelwiki.api.app:app --reload --port 8000  # or: uv run python main.py
```

Set `PUBLIC_BASE_URL=http://localhost:8000` to match the command above. For Vite hot
reload, run `VITE_API_PROXY=http://localhost:8000 npm run dev` from
`novelwiki/frontend` in a second terminal; it otherwise proxies to port 8001.

Sidecars are optional in dev. Without them, scanned-PDF OCR needs the configured Gemini
fallback and new narration cannot be generated. Without the Novelpia browser service,
ad gates require manual completion. The Compose sidecars expose no host
ports, so a host-run web process cannot reach them through `localhost:8077`, `:8078`,
or `:8079`;
run the web service in Compose to use its private service network, or configure separately
reachable local services and matching sidecar tokens.
