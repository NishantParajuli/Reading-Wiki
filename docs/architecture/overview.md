# Architecture overview

> **Audience:** everyone. Read this first. If terms like "hexagonal", "composition root",
> or "unit of work" are new to you, read [concepts/primer.md](../concepts/primer.md) first,
> then come back.

Tideglass (Python package name: `novelwiki`) is a **modular monolith**: one deployable
FastAPI process, one PostgreSQL database, one React SPA — but the *code inside* that single
process is divided into ten independently-owned **business modules**, organized as
**vertical slices**, each with **Clean/Hexagonal boundaries** inside it.

```
                          ┌──────────────────────────────────────────────────────┐
                          │                ONE DEPLOYABLE PROCESS                │
   Browser (React SPA) ──▶│  FastAPI (Platform Web)                              │
   python -m novelwiki.cli│  Typer CLI (Platform CLI runtime)                    │──▶ one PostgreSQL
   systemd AGY worker  ──▶│  3 in-process workers (import / TTS / generic jobs)  │    (pgvector + pg_trgm)
                          │                                                      │
                          │  identity  catalog  reading  acquisition  translation│──▶ filesystem (./data)
                          │  codex  narration  work  ai_execution  experience    │──▶ OpenRouter / Gemini
                          │        + platform + bootstrap + kernel + workflows   │──▶ OCR/TTS GPU sidecars
                          └──────────────────────────────────────────────────────┘
```

The three ideas in one sentence each:

1. **Modular monolith** — everything ships as one process and one database, so operations
   stay simple; but the *source code* is partitioned into modules with enforced boundaries,
   so the codebase behaves like a set of small services that happen to share a runtime.
2. **Vertical slices** — code is grouped by *business capability* (e.g. everything about
   translation lives in `novelwiki/modules/translation/`), not by technical kind (no global
   "models/", "views/", "controllers/" folders).
3. **Clean/Hexagonal boundaries inside each module** — within a module, business logic
   never imports web/database/provider code. It declares *ports* (interfaces) and the
   details are supplied from outside as *adapters*.

The decision record is [ADR 001](adr-001-modular-monolith.md). The final migration
evidence is [migration-completion.md](migration-completion.md) and
[migration-equivalence-final.md](migration-equivalence-final.md).

---

## The top-level map

Everything under `novelwiki/` falls into exactly one of five categories:

| Category | Directories | Role |
|---|---|---|
| **Business modules** | `novelwiki/modules/{identity,catalog,reading,acquisition,translation,codex,narration,work,ai_execution,experience}` | All business behavior; each owns specific DB tables and filesystem roots. |
| **Platform** | `novelwiki/platform/` | Technical infrastructure with no business rules: settings, DB pool + unit of work, FastAPI factory (middleware/CSP/CSRF), static file serving, audit sink, CLI runtime, and the architecture checker itself. |
| **Kernel** | `novelwiki/kernel/` | Tiny shared vocabulary: transport-neutral error types and the opaque transaction contracts. Everything may import kernel; kernel imports nothing. |
| **Workflows** | `novelwiki/workflows/` | Named cross-module *atomic* operations (e.g. `commit_translation`). Workflows own no SQL; they coordinate transaction-bound public capabilities of several modules inside one database transaction. |
| **Bootstrap (composition root)** | `novelwiki/bootstrap/` | The only place that knows how everything is wired together: builds the FastAPI app, registers routers, injects every dependency, starts/stops workers, owns the worker-handler registry and the CLI composition. |

Everything else at the `novelwiki/` top level (`api/`, `auth/`, `db/`, `jobs/`, `agy/`,
`ai_backend/`, `importer/`, `scraper/`, `ingest/`, `retrieval/`, `agent/`, `translate/`,
`tts/`, `quota.py`, `audit.py`, `ai_limits.py`, `config/`, `eval/`) is a **stable
compatibility surface**: passive import aliases and thin dependency-injecting wrappers kept
so external consumers (the ASGI deployment target, the CLI module path, evaluation-test
fixtures, operational scripts, the AGY plugin) keep working at their historical import
paths. Business modules are forbidden (and mechanically prevented) from using these paths
for internal communication. The authoritative list is
[stable-compatibility-entrypoints.md](stable-compatibility-entrypoints.md).

Outside the package:

| Path | Role |
|---|---|
| `main.py` | Convenience launcher: `uvicorn novelwiki.api.app:app` on `:8000`. |
| `novelwiki/frontend/` | React SPA (Vite). Built to `novelwiki/frontend/dist`, served same-origin by FastAPI. See [frontend/overview.md](../frontend/overview.md). |
| `sidecar/`, `sidecar-tts/` | Optional GPU sidecar services (PaddleOCR on `:8077`, OmniVoice TTS on `:8078`) with their own Dockerfiles. |
| `tests/`, `novelwiki/eval/` | Unit/architecture/contract tests and DB-backed integration suites. See [../testing.md](../testing.md). |
| `tools/` | `check_architecture.py` (boundary gate), `benchmark_queries.py`, `rehearsal_database.py`. |
| `scripts/` | `contracts.py` (snapshot regeneration), `test_backend.py` (integration launcher), backup-restore rehearsal, real-browser fixture. |
| `deploy/` | `novelwiki-agy-worker.service` systemd unit for the dedicated AGY host worker. |
| `implementation-plan/` | The migration plan that produced this architecture (historical, but it is the normative source for table ownership). |
| `data/` | Runtime data (BM25 indexes, assets, audio, import scratch). See [../data/filesystem-layout.md](../data/filesystem-layout.md). |

---

## The ten business modules

Each module is a vertical slice: it owns its HTTP endpoints, its worker/CLI adapters, its
application services, its domain rules, and its own tables. One-line summaries (full
reference: [../modules/README.md](../modules/README.md)):

| Module | Owns the business of… | Write-owned tables |
|---|---|---|
| **Identity** | accounts, sessions, OAuth, email tokens, rate limits, quotas, profiles, admin user management | `users`, `oauth_accounts`, `sessions`, `email_tokens`, `auth_rate_limits`, `quota_usage` |
| **Catalog** | the novel aggregate: metadata, ownership, visibility, per-user libraries, tag suggestions | `novels`, `library_entries`, `tag_suggestions` |
| **Reading** | chapters and the act of reading: progress, bookmarks, overlays, contributions, the trusted spoiler ceiling | `chapters`, `reading_progress`, `bookmarks`, `chapter_overlays`, `contributions` |
| **Acquisition** | getting text in: scraping sources, EPUB/PDF import jobs, extracted image assets | `sources`, `import_jobs`, `assets` |
| **Translation** | raw-chapter translation and the per-novel glossary | `translation_glossary` |
| **Codex** | the spoiler-safe knowledge base: chunks, entities, facts, relationships, events, retrieval, Ask, recap | `chunks`, `entities`, `entity_descriptions`, `entity_aliases`, `identity_links`, `entity_facts`, `relationships`, `events`, `extraction_state`, `wiki_cache`, `query_cache` |
| **Narration** | audiobook TTS jobs and the chapter-audio cache | `tts_jobs`, `chapter_audio` |
| **Work** | the generic durable-job system (scrape/codex/translate batches): scheduling, dedupe, leases, retries, quota settlement | `jobs` |
| **AI Execution** | *how* AI runs: backend policy (API vs AGY), provider gateways, cost controls, the AGY runner/workspaces, run records | `user_ai_backend_policies`, `ai_request_locks`, `provider_budget`, `ai_execution_runs`, `ai_worker_heartbeats` |
| **Experience** | cross-module *read-only* projections: home, activity feed, discover, library cards, profiles, health, cost estimates, admin dashboards | none (registered read-only projections only) |

Platform Database/Observability owns the two remaining tables: `app_migrations`,
`audit_events`. **Every one of the 39 tables has exactly one writer module** — the
authoritative table is [module-ownership.md](module-ownership.md), and the checker in
`tools/check_architecture.py` fails the build if any module's SQL touches a table it
doesn't own (reads across owners are only allowed inside Experience's registered
projections).

### Module dependency rules

- A module may import from another module **only** stable *types* (DTOs, error classes,
  `Protocol` interfaces) from that module's **`public.py`**. Never from its internals.
- **Executable capabilities are never imported across modules.** If Narration needs to
  resolve chapter text (a Reading capability), Narration declares its own port
  (`ChapterTextPort`) and Bootstrap injects a Reading-backed implementation at wiring time.
  This keeps the *executable* module graph acyclic and every dependency visible in one
  place.
- Anything that must write to two modules' tables **atomically** is a named workflow in
  `novelwiki/workflows/` — see
  [workflows-and-transactions.md](workflows-and-transactions.md).

---

## Inside one module: the hexagonal layers

Every module follows the same internal layout (full walkthrough with real code:
[module-anatomy.md](module-anatomy.md)):

```
novelwiki/modules/<name>/
├── public.py              ← the ONLY thing other modules may import: frozen DTOs,
│                            Protocol capability interfaces, stable errors
├── domain/                ← pure business rules & prompts; imports nothing but stdlib/kernel
├── application/           ← use cases (services/commands), ports (Protocols the module
│                            NEEDS), DTOs; no SQL, no HTTP, no provider SDKs, no pool
└── adapters/
    ├── inbound/           ← things that CALL the application: FastAPI routers (http.py),
    │                        Typer commands (cli.py), durable-worker loops (worker.py),
    │                        job handlers (jobs.py). Database-free.
    └── outbound/          ← things the application CALLS THROUGH PORTS: Postgres
                             repositories, provider clients, sidecar clients, filesystem,
                             bridges to other modules' public capabilities
```

The dependency arrows always point inward:
`inbound adapter → application → domain`, and `outbound adapter → application ports`
(an outbound adapter *implements* a port the application defined). The application layer
never knows whether it's being driven by HTTP, the CLI, or a worker, and never knows
whether its port is backed by Postgres, a fake in a unit test, or another module.

---

## Life of a request (worked example)

`PUT /api/novels/42/progress` — a reader finished a chapter:

1. **Platform Web** (`novelwiki/platform/web/factory.py`): the middleware stamps/propagates
   `X-Request-ID`, enforces CSRF (double-submit cookie), and applies security headers.
2. **Bootstrap** mounted the Reading router under `/api` with a router-level
   `Depends(current_user)` (`novelwiki/bootstrap/web.py`), so Identity's session dependency
   resolves the `tg_session` cookie → hashed token → `sessions` row → `users` row, and
   rejects with 401 if absent/expired.
3. **Reading inbound HTTP adapter**
   (`novelwiki/modules/reading/adapters/inbound/http.py::api_set_progress`) validates the
   Pydantic body and calls the injected `ReadingService`. The adapter contains no SQL.
4. **Reading application service** (`application/services.py`) applies the business rule —
   progress may only move to an existing chapter; `max_chapter_read` is monotonic (it never
   goes down, which is what makes the spoiler ceiling trustworthy) — through its
   repository port.
5. **Reading outbound adapter** (`adapters/outbound/postgres.py::PostgresReadingRepository`)
   executes the actual `INSERT … ON CONFLICT` against `reading_progress`, the table Reading
   owns.
6. Errors flow back as kernel `ApplicationError` subtypes (`NotFound`, `Forbidden`, …) and
   the inbound adapter translates them to HTTP status codes; the transport never leaks
   inward.

A background-job example (a codex build) additionally passes through Work's durable-job
system and the Bootstrap worker registry — traced end-to-end in
[../pipelines/background-jobs-and-quota.md](../pipelines/background-jobs-and-quota.md).

---

## The one product invariant

Everything in the codex subsystem serves a single hard rule:

> When a reader's ceiling is chapter *N*, no information from any chapter > *N* may appear
> in any codex entry, stat, answer, or recap.

It is enforced *structurally* — every codex-owned row carries a chapter key and every read
path filters `WHERE chapter <= ceiling` at the SQL/retrieval layer; the ceiling itself is
computed from server-observed reads (`reading_progress.max_chapter_read`), never from a
client-supplied number. The LLM is never trusted to withhold anything: it simply never
receives out-of-bounds text. Full treatment:
[../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

---

## Numbers worth knowing

| Fact | Value |
|---|---|
| Backend Python files / lines | ~401 files, ~37.7k lines |
| HTTP routes | 119 (snapshot: `tests/contracts/snapshots/routes.json`) |
| CLI commands | 13 (`tests/contracts/snapshots/cli.json`) |
| Database tables | 39, one writer each (`docs/architecture/module-ownership.md`) |
| Business modules | 10 + Platform |
| Named cross-module workflows | 8 (`novelwiki/workflows/`) |
| In-process durable workers | 3 (import, TTS, generic jobs) + 1 dedicated AGY host worker |
| Test suites | unit (`tests/unit`), architecture (`tests/architecture`), contracts (`tests/contracts`), DB-backed eval (`novelwiki/eval`), frontend unit + e2e |

## Where to go next

- How one module is built inside: [module-anatomy.md](module-anatomy.md)
- How it's all wired at startup: [composition-root.md](composition-root.md)
- Atomic cross-module writes: [workflows-and-transactions.md](workflows-and-transactions.md)
- The technical substrate: [platform.md](platform.md)
- How the rules are enforced mechanically: [enforcement.md](enforcement.md)
- Per-module deep dives: [../modules/README.md](../modules/README.md)
