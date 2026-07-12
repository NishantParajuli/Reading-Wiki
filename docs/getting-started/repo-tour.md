# Repository tour

Every top-level path and what lives there. Deep links go to the detailed docs.

```
wiki/
├── main.py                    # convenience launcher (uvicorn on :8000)
├── pyproject.toml + uv.lock   # Python project + locked deps (uv)
├── Dockerfile                 # 3-stage web image (SPA build → uv venv → slim runtime)
├── docker-compose.yml         # web + optional GPU sidecars on a private bridge
├── try_adapter.py             # scratch harness for developing scraper adapters
│
├── novelwiki/                 # ═══ THE BACKEND PACKAGE ═══
│   ├── modules/               # the 10 business modules (vertical slices)
│   │   ├── identity/          #   accounts, sessions, OAuth, quotas      → docs/modules/identity.md
│   │   ├── catalog/           #   novels, visibility, libraries          → docs/modules/catalog.md
│   │   ├── reading/           #   chapters, progress, overlays, ceiling  → docs/modules/reading.md
│   │   ├── acquisition/       #   scraping + EPUB/PDF import + assets    → docs/modules/acquisition.md
│   │   ├── translation/       #   translation + glossary                 → docs/modules/translation.md
│   │   ├── codex/             #   spoiler-safe knowledge base            → docs/modules/codex.md
│   │   ├── narration/         #   audiobook TTS                          → docs/modules/narration.md
│   │   ├── work/              #   generic durable jobs                   → docs/modules/work.md
│   │   ├── ai_execution/      #   API/AGY backends, cost controls        → docs/modules/ai-execution.md
│   │   └── experience/        #   cross-module read projections, admin   → docs/modules/experience.md
│   │   #  each: public.py + domain/ + application/ + adapters/{inbound,outbound}
│   │
│   ├── platform/              # technical substrate (no business rules)
│   │   #  config/settings.py · database/{pool,uow} · web/{factory,static} ·
│   │   #  observability/audit · auth re-exports · cli runtime · architecture/checks
│   ├── kernel/                # shared errors + opaque transaction contracts
│   ├── workflows/             # 8 named cross-module atomic operations
│   ├── bootstrap/             # THE composition root: web app assembly, DI wiring,
│   │                          # lifecycle, worker registry, CLI composition
│   │
│   ├── db/                    # schema.py (39-table idempotent DDL — a stable explicit
│   │                          # entrypoint), migrate_multiuser.py, legacy aliases
│   ├── frontend/              # React SPA (Vite)                        → docs/frontend/overview.md
│   ├── eval/                  # DB-backed integration test suites (*_tests.py)
│   │
│   └── api/ auth/ jobs/ agy/ ai_backend/ importer/ scraper/ ingest/ retrieval/
│       agent/ translate/ tts/ config/ quota.py audit.py ai_limits.py cli.py
│       #  ⚠ STABLE COMPATIBILITY ALIASES ONLY — passive re-exports/wrappers for
│       #  external consumers (ASGI target, CLI path, eval fixtures, scripts, AGY
│       #  plugin). Business modules may NOT import these internally (checker-
│       #  enforced). List: docs/architecture/stable-compatibility-entrypoints.md
│
├── sidecar/                   # PaddleOCR GPU sidecar (Dockerfile + ocr_server.py, :8077)
├── sidecar-tts/               # OmniVoice TTS sidecar (+ voices/ reference clips, :8078)
│
├── tests/
│   ├── unit/                  # pure unit tests (per module + kernel/platform/workflows)
│   ├── architecture/          # boundary rules as pytest
│   └── contracts/             # snapshot tests + snapshots/ (routes, openapi, cli,
│                              # schema, job states, responses, agy, frontend inventory)
├── tools/                     # check_architecture.py · benchmark_queries.py ·
│                              # rehearsal_database.py
├── scripts/                   # contracts.py (regen snapshots) · test_backend.py
│                              # (disposable-DB integration launcher) ·
│                              # rehearse-backup-restore.sh · real-browser fixtures
├── deploy/                    # novelwiki-agy-worker.service (systemd --user unit)
├── implementation-plan/       # the migration plan (normative for table ownership)
├── data/                      # runtime data (gitignored)                → docs/data/filesystem-layout.md
└── docs/                      # ← you are here                          → docs/README.md
```

## How to find things (task → entry point)

| I want to… | Start at |
|---|---|
| trace an HTTP endpoint | `rg 'path' tests/contracts/snapshots/routes.json` → the owning module's `adapters/inbound/http.py` |
| find who's allowed to do X | the module's application service → its Catalog/Identity ports |
| change SQL for table T | T's owner in [module-ownership](../architecture/module-ownership.md) → that module's `adapters/outbound/` |
| see how a dependency is wired | `novelwiki/bootstrap/web.py` (search the `*_dependency` name) |
| understand a background job | the kind's handler in `adapters/inbound/jobs.py` + [jobs pipeline](../pipelines/background-jobs-and-quota.md) |
| add a scraper site | `modules/acquisition/adapters/outbound/scraper/adapters.py` (+ `try_adapter.py` to iterate) |
| change a prompt | the module's `domain/prompts.py` |
| adjust a knob | [configuration.md](../operations/configuration.md) → `platform/config/settings.py` |
| know why it's built this way | `docs/architecture/adr-*.md` + `implementation-plan/` |

## Reading order for a new contributor

1. [what-is-tideglass.md](what-is-tideglass.md) — the product
2. [local-setup.md](local-setup.md) — run it
3. [../architecture/overview.md](../architecture/overview.md) — the shape
4. [../architecture/module-anatomy.md](../architecture/module-anatomy.md) — one module in depth
5. The module doc for whatever you're touching + its pipeline doc
6. [../architecture/enforcement.md](../architecture/enforcement.md) — before your first PR
