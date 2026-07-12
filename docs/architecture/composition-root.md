# The composition root (`novelwiki/bootstrap/`)

> **Audience:** anyone who needs to understand "where does X get wired?", "what runs at
> startup?", or "how do I inject a different implementation?".

Business modules declare *what they need* (ports); adapters declare *what they can do*.
Someone still has to decide which adapter satisfies which port, in what order things start,
and which handlers run which job kinds. That someone is **Bootstrap** — the only package
allowed to know about everything. Nothing in `novelwiki/bootstrap/` contains business
logic; every file is construction and wiring.

There is deliberately **no DI framework and no service locator**. Wiring is plain Python:
explicit imports, explicit constructor calls, explicit `dependency_overrides`. The one
"container" (`bootstrap/container.py::ApplicationContainer`) is a frozen dataclass holding
`settings` and the audit sink, and its docstring states the rule: *"created by entrypoints,
never used as a locator."*

---

## 1. Entrypoints and what each composes

| Entrypoint | Stable path | Composed by |
|---|---|---|
| Web/ASGI | `novelwiki.api.app:app` | re-exports `bootstrap/web.py::app` |
| CLI | `python -m novelwiki.cli` | re-exports `bootstrap/cli.py::app` |
| Standalone import worker | `python -m novelwiki.cli import-worker` | `bootstrap/acquisition_cli.py::run_standalone_import_worker` |
| Dedicated AGY host worker | `python -m novelwiki.agy.worker` (systemd) | wraps `modules/ai_execution/adapters/inbound/worker.py` with `bootstrap/ai_execution_worker.py` runtime |

## 2. The web app (`bootstrap/web.py`, 475 lines)

Read this file top to bottom and you know the entire runtime shape of the server:

1. **App creation** — `platform.web.factory.create_web_app(lifespan=…, seed_csrf_cookie=…)`
   builds the FastAPI instance with CORS, CSRF middleware, security headers, and
   request-ID plumbing (see [platform.md](platform.md)). Bootstrap passes in the Identity
   pieces the middleware needs (CSRF cookie setter + token generator) — Platform never
   imports a business module.

2. **Router mounting** — one `include_router` per inbound HTTP adapter:

   | Router (module) | Prefix | Auth gate |
   |---|---|---|
   | Identity auth (`identity/adapters/inbound/http.py`) | `/api/auth` | public (its own per-route limits) |
   | Reading, Work, Catalog, Acquisition, Experience projections, Codex, Translation, Identity account, Narration (TTS), Experience product | `/api` | router-level `Depends(current_user)` |
   | Experience admin (`experience/adapters/inbound/admin_http.py`) | `/api/admin` | router-level `Depends(require_admin)` |

   The order the routers appear here is the order FastAPI matches them; static files are
   mounted **last** so the SPA catch-all can't shadow `/api`.

3. **Dependency overrides** — the long middle of the file: for every `*_dependency` seam
   an inbound adapter declared, Bootstrap installs the real factory via
   `app.dependency_overrides[seam] = factory`. Examples of the three recurring shapes:

   - *Per-request connection-scoped service* (yield-style, releases the connection when
     the request ends):

     ```python
     async def _reading_service():
         pool = await init_db_pool()
         async with pool.acquire() as connection:
             yield ReadingService(
                 PostgresReadingRepository(connection),
                 CatalogAccessService(PostgresCatalogRepository(connection)),
             )
     app.dependency_overrides[reading_service_dependency] = _reading_service
     ```

   - *Pool-backed service* (returns a service holding the pool; fine for multi-query
     read paths): `_quota_service`, `_identity_session_service`, `_work_service`.

   - *Capability bundle* (a `SimpleNamespace` of functions when the seam wants a toolkit,
     not a class): `_identity_auth_runtime` (password hashing, token signing, OAuth,
     email senders), `_quota_projection`.

   Larger constructions are delegated to per-module builder files so `web.py` stays a
   table of contents: `bootstrap/{catalog,translation,narration,experience,work,
   identity_admin,codex_migration,reading_migration,acquisition,acquisition_routes}.py`,
   each exposing `build_…` functions.

4. **Platform surfaces last** — `mount_platform_surfaces(app, ensure_owner_assets=…)`
   adds `/health`, the public avatar mount (`/assets/_users`), and the SPA
   (`novelwiki/frontend/dist` with index-fallback routing).

## 3. Application lifecycle (`bootstrap/lifecycle.py`)

Startup/shutdown is an explicit, ordered list of `LifecycleHook`s executed by
`ApplicationLifecycle` (invoked from the FastAPI lifespan). Each hook has a name, optional
`start`/`stop` callables, a `fatal_start` flag (non-fatal hooks log and continue), and a
`shutdown_order` (independent of startup order). The production list, in startup order:

| # | Hook | Start does | Fatal? | Shutdown order |
|---|---|---|---|---|
| 1 | `schema` | `db.schema.init_database()` — create DB if missing, apply idempotent DDL | no (logs, continues) | – |
| 2 | `database_pool` | create the asyncpg pool; wire Work's quota-finalization UoW (`wire_work_quota_finalization`) | **yes** | 40 (last) |
| 3 | `identity_cleanup` | purge expired sessions/tokens/rate-limit rows | no | – |
| 4 | `multiuser_migration` | `db.migrate_multiuser.maybe_migrate()` — guarded, marker-protected legacy migration | **yes** | – |
| 5 | `import_worker` | build the Acquisition runtime + start the import worker loop | no | 10 (first) |
| 6 | `tts_worker` | configure + start the Narration worker (quota, chapter-text resolver via Reading gateway, sidecar client, worker state) | no | 20 |
| 7 | `jobs_worker` | configure + start the generic Work worker (`claim_next`, handler registry factory, repositories) | no | 30 |
| 8 | `agy_health` | if `AGY_ENABLED`, warn when no healthy dedicated-worker heartbeat exists | no | – |

Shutdown stops workers **before** closing the pool (10 → 20 → 30 → 40), so an in-flight
job can finish its last write. Worker `stop()`s cancel their loop tasks and wait.

Rationale for "workers inside the web process": one deployable. Import has a first-class
standalone CLI mode and, like the generic Work worker, is claim-lease safe with N>1
instances. TTS is different: it requeues every `generating` row at startup and is a
single-instance-per-database design (its advisory target lock prevents duplicate audio
targets but does not make lifecycle recovery multi-worker safe). See
[../pipelines/background-jobs-and-quota.md](../pipelines/background-jobs-and-quota.md).

## 4. The worker-handler registry (`bootstrap/workers.py`)

The generic Work worker doesn't know what a "scrape" is. Bootstrap builds a
`WorkerRegistry` mapping job kind → async handler, and injects a *factory* for it into the
worker runtime:

```
build_api_worker_registry()
├─ "scrape"       → acquisition.adapters.inbound.jobs.execute_scrape_job   (+ scraper fns bound to the acquisition runtime)
├─ "codex_build"  → codex.adapters.inbound.jobs.execute_codex_job          (+ chunk/embed/extract/bm25 bound to the codex runtime)
└─ "translate"    → translation.adapters.inbound.jobs.execute_translation_job (+ translate/seed fns bound to the translation runtime)
```

Handlers receive `(job, context)` where `context` is the worker's execution context
(cancel checks, progress updates, user loading) — again passed in, never imported.
Registering the same workload twice raises immediately (`ValueError`), so a typo can't
silently shadow a handler. The AGY worker builds its own registry variant
(`bootstrap/ai_execution_worker.py`) whose codex/translation handlers run the AGY
adapters instead.

## 5. Runtime bundles (`bootstrap/*_runtime.py`, `*_worker.py`)

Acquisition, Codex, and Translation application code takes an explicit `runtime` argument
— an immutable bundle of provider gateways, repositories, and cross-module capabilities.
Bootstrap owns the construction:

- `bootstrap/acquisition_runtime.py::build_acquisition_runtime` — parsers, OCR client +
  Gemini escalation, segmentation LLM, storage roots, Reading ingestion gateway, Catalog
  transaction factories, the import-commit UoW, quota/owner-spend checks.
- `bootstrap/codex_worker.py::build_codex_runtime` — chat/embedding/rerank gateways,
  BM25 manager access, Reading codex gateway, extraction-commit UoW factory, entity
  resolver, cost-control settings.
- `bootstrap/translation.py::build_translation_execution_runtime` — translate model
  gateway, glossary repositories, Reading translation query/commit capabilities, Work
  metering, prefetch settings. Also `build_glossary_service` /
  `build_translation_scheduling_service` for the HTTP side.

This is the mechanism behind the migration-completion claim that "Acquisition,
Translation, and Codex commands/workers receive immutable runtime bundles from Bootstrap.
Their application packages contain no mutable provider/work/repository locators."

## 6. The CLI (`bootstrap/cli.py` + `platform/cli.py`)

`novelwiki.cli` is a 9-line stable alias for `bootstrap/cli.py::app`, which:

1. imports the three feature Typer apps (Acquisition, Codex, Translation inbound `cli.py`)
   plus Platform's (`reset-db`);
2. calls each `configure_*` hook, handing over command factories from
   `bootstrap/feature_cli.py` / `bootstrap/acquisition_cli.py` (which build the same
   runtimes as the web/worker paths — CLI work and web work run identical application
   code);
3. assembles the commands into the **exact baseline order** (`add-novel`, `scrape`,
   `chunk`, `embed`, `extract`, `translate`, `import`, `import-batch`, `import-series`,
   `import-worker`, `rebuild-bm25`, `merge`, `reset-db`) so the CLI help surface matches
   the frozen contract snapshot byte-for-byte (semantically normalized).

`platform/cli_runtime.py::run_cli` gives every command a uniform asyncio bootstrap with
pool cleanup. `bootstrap/cli_services.py` holds the small composition helpers
(`create_system_novel` — the CLI's `SystemPrincipal("cli")` path through the
`create_novel_with_source` workflow — `merge_codex_entities`, `reset_database`).

## 7. Composition idioms worth copying

- **Lazy imports inside builders.** Nearly every `build_…` imports inside the function
  body. This keeps import-time side effects near zero, breaks would-be import cycles, and
  makes each builder's true dependency set explicit at the call site.
- **`SimpleNamespace` for toolkits, classes for services.** When a seam needs a bag of
  functions (auth runtime, quota projection, worker runtimes at the inbound edge),
  Bootstrap passes a namespace; when it needs behavior + state, it constructs a class.
- **Factories over instances for per-job state.** The worker runtime takes
  `registry_factory` / `worker_state_factory`, not prebuilt instances — each poll/job gets
  fresh construction where that matters.
- **Bootstrap depends on everything; nothing depends on Bootstrap.** If you find yourself
  importing `novelwiki.bootstrap.*` from inside a module, you're inverting the
  architecture — declare a port instead.
