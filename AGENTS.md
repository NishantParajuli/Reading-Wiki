# Repository agent instructions

These instructions apply to every AI-assisted change in this repository.

## Documentation is part of the change

- Treat documentation as part of the implementation, not as optional follow-up work.
- For every change, assess whether it affects user-visible behavior, APIs or CLI commands,
  contracts, schema or storage, configuration, architecture or ownership, jobs and pipelines,
  frontend workflows, security, testing, CI/CD, deployment, or operator procedures.
- When an area is affected, update its living documentation in the same change. Do not defer
  the documentation to another PR unless the user explicitly excludes it from the task.
- Pure refactors, tests, formatting, and internal fixes that do not change any documented fact
  do not require artificial documentation edits. In that case, state
  `Documentation impact: none` and the reason in the final response.
- Documentation must describe the implementation in the resulting diff. Do not document
  planned or assumed behavior as though it already exists.
- Search `README.md` and `docs/` for renamed symbols, paths, commands, configuration keys,
  counts, and behavior. Keep examples and operational commands executable and current.
- When adding, removing, or relocating a documentation page, update `docs/README.md` and the
  root `README.md` documentation map where applicable.

Use `docs/README.md` as the documentation map:

| Change area | Primary documentation |
|---|---|
| Product concepts and setup | `docs/getting-started/`, `docs/concepts/`, root `README.md` |
| Architecture, boundaries, workflows | `docs/architecture/` |
| Module behavior and ownership | `docs/modules/` |
| Background jobs and AI/data pipelines | `docs/pipelines/` |
| HTTP API and CLI behavior | `docs/api/` |
| Database schema and filesystem layout | `docs/data/` |
| Frontend behavior and structure | `docs/frontend/` |
| Configuration, security, deployment, CI/CD, rollback | `docs/operations/`, `docs/release-runbook.md` |
| Test commands and quality gates | `docs/testing.md`, `docs/architecture/enforcement.md` |

After an intentional external contract change, regenerate contract snapshots with
`uv run python scripts/contracts.py --update`, review the generated diff, and update the
corresponding API, schema, CLI, or pipeline documentation.

ADRs, migration reports, and measured baselines are historical records. Do not rewrite them
to describe current behavior. Add a new ADR when a new architectural decision needs a durable
record, and update living architecture pages separately.

Before completion, review the full diff for documentation accuracy, run the relevant tests,
and run `git diff --check`.

## Review guidelines

- Flag a behavior-changing diff when its living documentation is missing or materially stale.
- Accept an explicit no-documentation-impact explanation only when the diff changes no
  documented behavior, contract, architecture, configuration, or operating procedure.
- Check that documentation describes the code in the same diff and does not present future
  work as complete.
- Match review severity to impact: stale deployment, security, contract, or data-integrity
  guidance is more serious than a missing low-level implementation note.
