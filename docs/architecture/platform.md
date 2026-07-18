# Platform (`novelwiki/platform/`)

> **Audience:** anyone touching infrastructure: settings, DB access, middleware, static
> serving, audit, or the architecture checker.

Platform is the technical substrate every module stands on. It holds **zero business
rules** and imports **no business module** (the two deliberate seams where business code
is *handed in* are noted below). Modules import Platform freely; Platform never imports
back.

```
novelwiki/platform/
├── config/settings.py        # every runtime setting (pydantic-settings, .env)
├── database/
│   ├── pool.py                # module-global asyncpg pool (init/get/close)
│   └── uow.py                 # AsyncpgUnitOfWork + TransactionBindings
├── web/
│   ├── factory.py             # create_web_app(): CORS, CSRF, CSP, request-id middleware
│   ├── static.py              # /health, avatar mount, SPA static serving
│   └── app.py                 # composed-app re-export plumbing
├── auth.py                    # re-export of Identity's web dependencies (see note)
├── observability/
│   ├── audit.py               # append-only audit events + request-id contextvar
│   └── logging.py             # JSON formatter + async-safe structured context
├── cli.py / cli_runtime.py    # reset-db command + uniform async CLI runner
└── architecture/checks.py     # the machine-readable architecture rules (394 lines)
```

## 1. Configuration (`platform/config/settings.py`)

A single `Settings(BaseSettings)` class loaded from the environment and
`.env` (`extra="ignore"`). Import it as `from novelwiki.platform.config import settings`.
Highlights of the structure (the full annotated reference is
[../operations/configuration.md](../operations/configuration.md)):

- **Database** (`DATABASE_URL`, `DB_SUPERUSER_URL`) — plain `postgresql://` scheme; asyncpg
  connects directly (not the SQLAlchemy dialect form).
- **Model routing** — `MODEL_FLASH`/`MODEL_PRO` ("Flash reads, Pro thinks"),
  `MODEL_TRANSLATE`, `SEGMENT_MODEL`, `EMBED_MODEL`+`EMBED_DIM`, `RERANK_MODEL`; native
  DeepSeek V4 generation when its key is configured, OpenRouter for other generation
  plus embeddings/reranking, and Gemini vision settings for OCR escalation.
- **Retrieval knobs** — chunk sizes, RRF constant, rerank depth, agent iteration cap,
  BM25 index path and thread offload.
- **Cost controls** — the `ASK_*` denial-of-wallet family, quotas (`DEFAULT_QUOTA_*`),
  Gemini daily budget.
- **Workers** — heartbeat/lease/attempt settings for the import and generic job workers.
- **Logging** — format/level, service/environment tags, HTTP events, and job-progress
  controls.
- **AGY** — a large, *validated* block (a `@model_validator` enforces sane ranges for
  concurrency, timeouts, batch sizes, retention, and non-empty model names; bad AGY
  config refuses to boot).
- **Auth/web** — session/CSRF cookie names, TTLs, rate-limit windows, CORS origins,
  cookie security, SMTP, OAuth client credentials, bootstrap admin.
- **Sidecars** — URLs, enablement, and the shared/per-service auth tokens with the
  `ocr_sidecar_token`/`tts_sidecar_token` effective-value properties.

## 2. Database (`platform/database/`)

- **`pool.py`** — one module-global asyncpg pool (`min_size=1, max_size=10`).
  `init_db_pool()` is idempotent; `get_db_pool()` lazily initializes;
  `close_db_pool()` runs at shutdown (lifecycle hook, shutdown order 40 = last).
  The architecture rule: **only outbound adapters and Bootstrap may touch the pool** —
  "pool initialization in non-outbound layers" is a checker violation class that was
  burned to zero.
- **`uow.py`** — the kernel `UnitOfWork` implementation used by workflows: one acquired
  connection + one explicit transaction per application operation, with
  `TransactionBindings.bind(capability)` constructing memoized connection-bound module
  services from a Bootstrap-supplied factory map. Details and usage:
  [workflows-and-transactions.md](workflows-and-transactions.md).

Schema DDL is *not* here: `novelwiki/db/schema.py` (and `db/migrate_multiuser.py`) remain
explicit, stable database entrypoints (see
[../data/database-schema.md](../data/database-schema.md)).

## 3. Web infrastructure (`platform/web/`)

### `factory.py::create_web_app(*, lifespan, seed_csrf_cookie)`

Builds the FastAPI instance with *security policy only* (no routes):

- **CORS** — explicit origins from `ALLOWED_ORIGINS` with credentials enabled (a `*`
  origin can't be used with cookies, so the list is explicit).
- **One `http` middleware** doing five jobs per request:
  1. **Request-ID** — honor an incoming `X-Request-ID` (truncated to 64 chars) or mint
     one; store it in the audit contextvar for the request's lifetime; echo it on the
     response. Every audit event written during the request carries it.
  2. **CSRF** — for any non-safe method under `/api`: the request must present a header
     (`x-tideglass-csrf` or `x-csrf-token`) equal (constant-time `hmac.compare_digest`)
     to the `tg_csrf` cookie. The five public auth mutations
     (`/api/auth/{register,login,request-reset,reset,verify}`) can't have a CSRF cookie
     yet, so they instead require the custom header `x-tideglass-request: 1` (a
     cross-site form can't send custom headers). Failures are 403 before any handler runs.
  3. **Security headers** — `X-Content-Type-Options: nosniff`,
     `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, and a CSP
     (`default-src 'self'`, no external connect/object, `frame-ancestors 'none'`).
  4. **CSRF cookie seeding** — a session cookie without a CSRF cookie gets one issued
     (via the Identity-supplied `seed_csrf_cookie` callback — the seam through which the
     business token generator is *handed in*).
  5. **Request logging** — emit a completion or failure event with request ID, method,
     path/route, status, client address, response size, duration, and traceback on an
     exception. Request bodies and query strings are not logged.

### `static.py::mount_platform_surfaces(app, *, ensure_owner_assets)`

Mounted after all API routers: `GET /health`; the public avatar directory
(`ASSET_DIR/_users` at `/assets/_users` — avatars are the only intentionally-public
assets); and the SPA. `SpaStaticFiles` adds two behaviors: hashed build assets
(`/assets/` inside the dist) get `Cache-Control: public, max-age=31536000, immutable`
while everything else is `no-cache`, and a 404 for an extension-less path serves
`index.html` so client-side routes (`/library`, `/n/42/read/12`) deep-link correctly.
Novel/import assets are **not** served from here — they go through the access-controlled
`/api/assets/...` endpoints (Acquisition).

### `auth.py`

A re-export module: `current_user`, `optional_user`, `require_admin`, `require_verified`,
`rate_limit` — implemented by Identity, published at a Platform path so other inbound
adapters and Bootstrap depend on a stable location rather than on Identity's internals.
(This is a *composition* convenience, one of the two sanctioned seams, not Platform
containing auth logic.)

## 4. Observability (`platform/observability/`)

The durable audit facility in `audit.py` provides:

- `new_request_id()` / `set_request_id()` / `reset_request_id()` — a `contextvars`-based
  request-id, set by the web middleware and readable anywhere down-stack without passing
  it through every signature.
- `FunctionAuditSink` / `record(event, user_id=…, novel_id=…, data=…)` — appends to the
  `audit_events` table (owned by Platform Observability): job lifecycle
  (`job.created`, `job.done`, `job.failed`…), quota movements (`quota.refund`), auth and
  admin actions. Fire-and-forget writes: an audit failure never breaks the business
  operation.

`logging.py` owns the operational stream:

- `configure_logging()` installs a shared JSON/console formatter and routes Uvicorn
  error/application loggers through it for the web, CLI, and dedicated AGY entrypoints.
  Uvicorn's raw-target access logger is disabled; the request middleware owns sanitized
  access events without query strings.
- `log_context()` uses `contextvars` to propagate job, worker, backend, run, and ownership
  fields through nested async calls and child tasks.
- `log_event()` adds a stable event name and queryable fields. JSON output includes timing,
  source/process identity, request ID, and active exception tracebacks.
- Common credential shapes are redacted. Lifecycle code intentionally excludes story
  content, prompts, provider/AGY output, bodies, and raw job options.

Worker adapters establish context at claim time; deep scraper/translation/codex/provider
logs inherit the actual `job_kind` and `job_id` without threading them through every
function. See [../operations/logging.md](../operations/logging.md) for the event schema and
Grafana/Loki operations.

## 5. CLI runtime (`platform/cli.py`, `platform/cli_runtime.py`)

`cli_runtime.run_cli(coro)` gives every Typer command the same asyncio entry (loop setup,
pool teardown, clean Ctrl-C). `platform/cli.py` contributes the one platform-owned
command, `reset-db` (interactive confirm unless `--force`; drops the 38 tables in the
historically frozen `ALL_TABLES` list, then re-applies all DDL). The omitted
`auth_rate_limits` table survives reset by ADR-002 compatibility policy, so “reset” is
not a literal empty-schema operation.

## 6. The architecture checker (`platform/architecture/checks.py`)

Platform owns the *rules as code* — 394 lines of AST/text analysis over the production
tree exposing the violation finders that `tools/check_architecture.py` and
`tests/architecture/test_architecture.py` run:

- `table_boundary_violations` — SQL literals anywhere in production code are parsed for
  table reads/writes and checked against the ownership registry (writes by non-owners are
  always violations; cross-owner reads are only legal inside Experience's registered
  projections and other approved read surfaces).
- `module_dependency_cycles` — the alias-aware executable import graph between modules
  must be acyclic.
- `cross_module_import_violations` — module A importing module B anywhere but
  `modules/B/public.py`.
- `legacy_facade_import_violations` — a business module importing a compatibility path
  (`novelwiki.auth.*`, `novelwiki.jobs.*`, …) for internal communication.
- `inbound_database_violations` — SQL/pool usage in any `adapters/inbound/` file.
- `frontend_boundary_violations` — bans the deleted global API/query facades, internal
  cross-slice imports, and growth beyond reviewed route-screen size limits. Endpoint
  inventories themselves are frozen separately by the contract snapshot.
- `layer_dependency_violations`, `public_surface_violations` (strict mode) — the full
  Clean Architecture layer matrix and public-surface shape rules.

There are **no count-based waivers**: the tools exit non-zero while any violation exists
(see [enforcement.md](enforcement.md) and the burned-down ledger in
[architecture-debt.md](architecture-debt.md)).
