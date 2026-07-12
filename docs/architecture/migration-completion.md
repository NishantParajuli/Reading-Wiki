# Modular-monolith migration finalization status

The target remains one FastAPI/React deployable and one PostgreSQL database. Runtime ownership is
now divided among ten business modules plus Platform; no service split or topology change was made.

## Final ownership evidence

- All 39 schema tables have exactly one writer in the ownership registry.
- Module SQL literals are checked for both cross-owner reads and writes.
- All inbound HTTP and worker adapters are database-free.
- The executable module graph is acyclic and cross-module Python imports target `public.py`.
- Cross-owner job/quota finalization uses transaction-bound owner APIs in one named
  Unit of Work. Initial AI scheduling intentionally retains guarded compensation as
  recorded in ADR 003 and is not described as crash-atomic.
- Codex extraction is a named Reading + Codex workflow. The coordinator locks and verifies the
  Reading source snapshot, then invokes transaction-bound Codex capabilities without exposing an
  asyncpg connection through a port.
- Experience registers every approved composite read, including operational/admin and job+AI-run
  views, and contains no write SQL.
- Work, AI, Acquisition, and Narration workers delegate claimed-job state-machine decisions to
  application services. Inbound worker code retains polling, leases, heartbeats, concrete-provider
  translation, and stable external entrypoints; Bootstrap owns handler registries and lifecycle.
- Acquisition, Translation, and Codex commands/workers receive immutable runtime bundles from
  Bootstrap. Their application packages contain no mutable provider/work/repository locators.
- The CLI entrypoint is composition-only and resource lifecycle is Platform-owned. Acquisition,
  Codex, and Translation pipelines are application commands built by Bootstrap; Typer adapters
  validate arguments and render results. Main and all 13 subcommand help surfaces match baseline.
- Experience keeps its SQL projections read-only. Identity, AI Execution, and Work admin mutations
  are injected through Experience-owned application ports, and recap execution is Codex-owned.
- Bootstrap owns service/router/dependency/lifecycle composition. Platform Web owns the FastAPI
  factory, security and CSRF middleware, health/static mounts, and SPA fallback/cache behavior; the
  stable ASGI import path is unchanged.
- The 2,166-line legacy router, per-module legacy HTTP bridges, and frontend global API facade are
  deleted. `novelwiki.api.routes` is a SQL-free stable direct-call wrapper only; FastAPI mounts
  native module routers.
- Reader, Manage, Import, Admin, and Account route screens are composition-oriented and enforced by
  reviewed size limits. All route screens, tags, TOC, and narration components now live in their
  owning frontend modules; cross-module imports use public indexes/API/query surfaces.

## Automated release gates

The GitHub Actions workflow defines pgvector-backed backend tests, architecture checks, compile checks, runtime
performance budgets,
budgets, contract snapshots, Docker Compose validation, frontend unit tests, production build, and
the mocked Chromium suite. Local release verification additionally runs the nine-path real-backend
suite through `scripts/test_real_browser.py`. The committed OpenAPI, route, representative response,
CLI, schema, and job-state snapshots
remain the compatibility authority.

Performance is ratcheted through `performance-baseline.json`: query plans remain bounded, Health and
Discover are measured through complete ASGI requests, and transactional worker-claim throughput has
a minimum rate. The budgets intentionally include environment headroom and require an explained
review to change.

Local verification evidence is recorded in `migration-equivalence-final.md`. Remote GitHub/Actions
verification was explicitly excluded from this finalization run and is not presented as evidence.

## Release boundary

The repository includes a destructive-safe, disposable backup/restore rehearsal and an operator
release/rollback runbook. Running the production backup, deploying an image, and observing the live
instance are operator-authorized actions; they are not performed by the source migration itself.

The disposable rehearsal was executed successfully again on 2026-07-12 using version-matched
PostgreSQL client/server tooling: a custom
format dump was restored into a separate database and the complete public table catalog and every
table row count matched before both rehearsal databases were removed.
