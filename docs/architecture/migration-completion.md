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
- Experience registers every approved composite read, including operational/admin and job+AI-run
  views, and contains no write SQL.
- Work and AI workers dispatch through composition-owned registries; feature handlers live with
  Acquisition, Translation, and Codex. Acquisition and Narration inbound workers still contain
  substantial state-machine orchestration and require a further application-service extraction.
- The CLI entrypoint is composition-only and resource lifecycle is Platform-owned, with an exact
  baseline help snapshot. Acquisition's Typer adapter still contains import pipeline orchestration
  that must move behind application commands.
- The 2,166-line legacy router, per-module legacy HTTP bridges, and frontend global API facade are
  deleted. `novelwiki.api.routes` is a SQL-free stable direct-call wrapper only; FastAPI mounts
  native module routers.
- Reader, Manage, Import, Admin, and Account route screens are composition-oriented and enforced by
  reviewed size limits. Endpoint calls are owned by frontend feature modules.

## Automated release gates

The GitHub Actions workflow defines pgvector-backed backend tests, architecture checks, compile checks, query-plan
budgets, contract snapshots, Docker Compose validation, frontend unit tests, production build, and
the ten-path Chromium suite. The committed OpenAPI, route, CLI, schema, and job-state snapshots
remain the compatibility authority.

Performance is ratcheted through `performance-baseline.json`: Library composite reads and Work,
Import, and Narration `SKIP LOCKED` claim plans must remain inside reviewed PostgreSQL total-cost
budgets. The budgets intentionally include environment headroom and require an explained review to
change.

The final local working tree must be committed and pushed before its remote Actions run can be
observed; local verification evidence is recorded in `migration-equivalence-final.md`.

## Release boundary

The repository includes a destructive-safe, disposable backup/restore rehearsal and an operator
release/rollback runbook. Running the production backup, deploying an image, and observing the live
instance are operator-authorized actions; they are not performed by the source migration itself.

The disposable rehearsal was executed successfully on 2026-07-11 against PostgreSQL 18: a custom
format dump was restored into a separate database and the complete public table catalog and every
table row count matched before both rehearsal databases were removed.
