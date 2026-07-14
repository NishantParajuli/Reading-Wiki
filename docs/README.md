# Tideglass documentation

Complete documentation for the Tideglass reading platform (`novelwiki` codebase). The
architecture is a **modular monolith organized as vertical slices with Clean/Hexagonal
boundaries inside each module** — if that sentence isn't fully transparent yet, start
with the primer.

This index distinguishes **living references** (expected to describe `HEAD`) from
**historical records** (ADRs, migration evidence, and measured baselines). Historical
records remain valuable evidence, but their dated counts and verification results are
not promises about a later checkout.

## Reading paths

- **Brand new to the project (or to these concepts):**
  [what-is-tideglass](getting-started/what-is-tideglass.md) →
  [concepts/primer](concepts/primer.md) →
  [local-setup](getting-started/local-setup.md) →
  [repo-tour](getting-started/repo-tour.md) →
  [architecture/overview](architecture/overview.md)
- **Experienced dev, new to this repo:**
  [architecture/overview](architecture/overview.md) →
  [module-anatomy](architecture/module-anatomy.md) →
  [composition-root](architecture/composition-root.md) →
  [enforcement](architecture/enforcement.md) → the module doc you're touching
- **Operating an instance:**
  [deployment](operations/deployment.md) →
  [configuration](operations/configuration.md) →
  [structured logging](operations/logging.md) →
  [release-runbook](release-runbook.md) →
  [security](operations/security.md)

## Getting started

| Doc | Contents |
|---|---|
| [what-is-tideglass](getting-started/what-is-tideglass.md) | product tour, the invariant, external services |
| [local-setup](getting-started/local-setup.md) | zero → running instance with a novel |
| [repo-tour](getting-started/repo-tour.md) | every top-level path + task→entry-point table |

## Concepts

| Doc | Contents |
|---|---|
| [primer](concepts/primer.md) | every underlying concept from first principles (web, async, DB, patterns, AI/retrieval, ops) |
| [spoiler-safety](concepts/spoiler-safety.md) | THE invariant: trusted ceilings and their enforcement points |
| [glossary](concepts/glossary.md) | project terms A–Z |

## Architecture

| Doc | Contents |
|---|---|
| [overview](architecture/overview.md) | the whole shape: categories, modules, request lifecycle |
| [module-anatomy](architecture/module-anatomy.md) | the standard slice layout, layer rules, naming, how to extend |
| [composition-root](architecture/composition-root.md) | bootstrap: app assembly, DI, lifecycle, worker registry, CLI |
| [workflows-and-transactions](architecture/workflows-and-transactions.md) | kernel, unit of work, 7 transactional workflows + the guarded-compensation scheduler |
| [platform](architecture/platform.md) | settings, pool/UoW, web factory (CSRF/CSP), static, audit, checker |
| [enforcement](architecture/enforcement.md) | every automated gate + pre-merge checklist |
| [module-ownership](architecture/module-ownership.md) | human-readable table-writer and workflow-participant map; executable authority is `TABLE_OWNERS` |
| ADRs [001](architecture/adr-001-modular-monolith.md) · [002](architecture/adr-002-baseline-defects.md) · [003](architecture/adr-003-ai-scheduling-consistency.md) | decisions: the architecture, baseline defects, AI scheduling consistency |
| [migration-completion](architecture/migration-completion.md) · [migration-equivalence-final](architecture/migration-equivalence-final.md) · [architecture-debt](architecture/architecture-debt.md) | dated migration evidence and debt burn-down *(historical)* |
| [performance-baseline.json](architecture/performance-baseline.json) | executable query/endpoint/worker budgets consumed by `tools/benchmark_queries.py` |
| [stable-compatibility-entrypoints](architecture/stable-compatibility-entrypoints.md) | the sanctioned legacy import paths |

## Future implementation plans

Plans describe possible future work and are **not** living authority. Re-check them
against `HEAD` and the living references above before implementation.

| Plan | Contents |
|---|---|
| [PostgreSQL-centered platform evolution](../implementation-plan/postgres-platform-evolution-plan.md) | TTS leadership, separate worker roles, versioned migrations, storage reconciliation, durable event fan-out with `LISTEN/NOTIFY`, cache lifecycle, queue operations, observability, and recovery |

## Module reference — [map & dependency graph](modules/README.md)

[identity](modules/identity.md) · [catalog](modules/catalog.md) ·
[reading](modules/reading.md) · [acquisition](modules/acquisition.md) ·
[translation](modules/translation.md) · [codex](modules/codex.md) ·
[narration](modules/narration.md) · [work](modules/work.md) ·
[ai-execution](modules/ai-execution.md) · [experience](modules/experience.md)

## Pipelines (end-to-end walkthroughs)

| Doc | Contents |
|---|---|
| [background-jobs-and-quota](pipelines/background-jobs-and-quota.md) | the shared durable-job machinery + the money lifecycle (read first) |
| [scraping](pipelines/scraping.md) | adapters, multi-source stitching, SSRF boundary |
| [file-import](pipelines/file-import.md) | upload → parse → OCR → segment → review → commit |
| [translation](pipelines/translation.md) | engine, glossary, atomic commits, overlays, AGY staging |
| [codex-build-and-ask](pipelines/codex-build-and-ask.md) | chunk/embed/extract/link/index; retrieval; the agent; recap |
| [narration](pipelines/narration.md) | TTS worker, sidecar, caching, invalidation |
| [ai-backends](pipelines/ai-backends.md) | API vs AGY: selection, hardened execution, failure paths |

## Data & API

| Doc | Contents |
|---|---|
| [data/database-schema](data/database-schema.md) | all 39 created tables, table-by-table column semantics, including the intentional 38-table reset-list quirk |
| [data/filesystem-layout](data/filesystem-layout.md) | on-disk roots, serving rules, cleanup, backup |
| [api/http-api](api/http-api.md) | annotated route families + auth/CSRF/error conventions |
| [api/http-route-inventory](api/http-route-inventory.md) | exact method/path/endpoint-name inventory for all 119 routes |
| [api/cli](api/cli.md) | all 13 commands + module entrypoints + recipes |

## Frontend

| Doc | Contents |
|---|---|
| [frontend/overview](frontend/overview.md) | stack, slice structure, routing, data layer, reader, testing |

## Operations

| Doc | Contents |
|---|---|
| [operations/deployment](operations/deployment.md) | topology, image, compose, first boot, deploying changes |
| [operations/configuration](operations/configuration.md) | every setting with defaults + prod checklist |
| [operations/logging](operations/logging.md) | JSON event schema, worker/job coverage, Grafana/Loki queries, incident use |
| [operations/security](operations/security.md) | the full control inventory, layer by layer |
| [testing](testing.md) | how to run every suite |
| [release-runbook](release-runbook.md) | release & rollback procedure |
| [agy-operator-runbook](agy-operator-runbook.md) | enabling/operating the AGY host worker |

## Keeping these docs honest

AI-assisted changes follow the repository-wide documentation policy in
[`AGENTS.md`](../AGENTS.md). It requires a documentation-impact assessment for every change
and same-change updates whenever living documentation would otherwise become stale.

Use this precedence when prose and code disagree:

1. Runtime code and executable registries (`TABLE_OWNERS`, router composition, settings,
   schema DDL) are the implementation truth.
2. Contract snapshots (`tests/contracts/snapshots/`) freeze externally observable
   routes, OpenAPI, CLI, DDL, job states, response examples, AGY contracts, and frontend
   inventory.
3. Living reference pages explain those artifacts.
4. ADRs explain why decisions were made; migration reports describe what was verified at
   the date/commit printed in the report.

After an intentional contract change, run
`uv run python scripts/contracts.py --update`, review the JSON diff, and update the
corresponding reference (`api/http-api.md`, `api/http-route-inventory.md`, `api/cli.md`,
`data/database-schema.md`, or `pipelines/background-jobs-and-quota.md`). Module and
pipeline docs should change in the same PR as their code. Before merging documentation,
also verify local Markdown targets and anchors and search renamed symbols/paths across
`README.md` and `docs/`.
