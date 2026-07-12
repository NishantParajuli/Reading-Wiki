# Tideglass documentation

Complete documentation for the Tideglass reading platform (`novelwiki` codebase). The
architecture is a **modular monolith organized as vertical slices with Clean/Hexagonal
boundaries inside each module** — if that sentence isn't fully transparent yet, start
with the primer.

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
| [workflows-and-transactions](architecture/workflows-and-transactions.md) | kernel, unit of work, the 8 named workflows |
| [platform](architecture/platform.md) | settings, pool/UoW, web factory (CSRF/CSP), static, audit, checker |
| [enforcement](architecture/enforcement.md) | every automated gate + pre-merge checklist |
| [module-ownership](architecture/module-ownership.md) | table-writer registry + workflow owners *(migration artifact)* |
| ADRs [001](architecture/adr-001-modular-monolith.md) · [002](architecture/adr-002-baseline-defects.md) · [003](architecture/adr-003-ai-scheduling-consistency.md) | decisions: the architecture, baseline defects, AI scheduling consistency |
| [migration-completion](architecture/migration-completion.md) · [migration-equivalence-final](architecture/migration-equivalence-final.md) · [architecture-debt](architecture/architecture-debt.md) | migration evidence (historical) |
| [stable-compatibility-entrypoints](architecture/stable-compatibility-entrypoints.md) | the sanctioned legacy import paths |

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
| [data/database-schema](data/database-schema.md) | all 39 tables, column-by-column, with ER sketch |
| [data/filesystem-layout](data/filesystem-layout.md) | on-disk roots, serving rules, cleanup, backup |
| [api/http-api](api/http-api.md) | all 119 routes + auth/CSRF/error conventions |
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
| [operations/security](operations/security.md) | the full control inventory, layer by layer |
| [testing](testing.md) | how to run every suite |
| [release-runbook](release-runbook.md) | release & rollback procedure |
| [agy-operator-runbook](agy-operator-runbook.md) | enabling/operating the AGY host worker |

## Keeping these docs honest

The contract snapshots (`tests/contracts/snapshots/`) are the machine-checked source of
truth for routes, CLI, schema, and job states — when they change, update the
corresponding reference page here (`api/http-api.md`, `api/cli.md`,
`data/database-schema.md`, `pipelines/background-jobs-and-quota.md`). Module docs should
change in the same PR as significant module-shape changes.
