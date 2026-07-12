# Migration equivalence report

Verified locally again on 2026-07-12 against baseline commit
`c244a1fa6e562747041fee0fba5ce455402621de` and migration starting point
`97c9618`.

## Reproducible baseline comparison

A detached worktree was created at the baseline and the same deterministic JSON
normalization used by `scripts/contracts.py` was applied to both applications.

| Artifact | SHA256 (baseline and current) |
|---|---|
| CLI command inventory | `4443177d6e20c3a0444b4974d31ce53660ea9191a6b5c7b858e9311dee068071` |
| Job states | `6ae8829c9118eec7f1a0249aea3670a6d48a22d3d7e4c3f5f3136fd7ba06796f` |
| OpenAPI | `8d0f87ec184549c05b6bb45621506f21207538dfcc6f5cec7df84da018a091c2` |
| Route inventory | `7cb4fd719e5f6a5a6b0bde48b55ae8121ab95d52a5e62e2c3e862907981f8047` |
| Schema/DDL | `6cc8bf02c4a19399438a1aa9d9dc94a23b318f17cee5b7d81005ddd1d84dc467` |

The main CLI help and every one of the 13 subcommand help surfaces are captured
semantically with Typer's `CliRunner`: ANSI styling, Rich table borders and host-dependent
line wrapping are discarded, while every word, option, default and command order remains.
Applying that normalization to the previously approved raw snapshot produces the exact current
artifact (`db528ae00217ff230a73fec3bfbc2a294865879fe368a69a21b4e14036c1675b`).

The repository now also snapshots CLI help, representative success/error JSON for every route
family, AGY manifest schemas/plugin file hashes, and frontend route/module-endpoint inventories.

## Local release evidence

- Backend with disposable PostgreSQL/pgvector: 524 passed.
- Architecture/contracts/unit gate: 311 passed.
- Python compilation: passed.
- Contract snapshot verification: passed.
- Frontend Vitest: 19 passed.
- Frontend production build: passed.
- Mocked Chromium paths: 10 passed.
- Real browser/FastAPI/PostgreSQL suite: all nine required paths passed against a database created
  and destroyed by `scripts/test_real_browser.py`. Coverage includes session re-gating,
  Library/Discover, trusted progress/bookmarks, overlay conflict resolution, real EPUB
  review/commit, job cancellation/Activity, cached spoiler-clamped Ask, authorized HTTP Range
  audio, and an admin quota mutation. Provider boundaries use seeded cache/audio fixtures only.
- Docker Compose validation: passed.
- Runtime performance gate: passed. Query costs were `33.02/200`, `8.19/10`, `9.67/10`,
  and `8.19/10`; Health/Discover ASGI p95 was `6.90/100 ms` and `22.80/500 ms`; transactional
  worker claims measured `7,422/s` against a `100/s` minimum.
- Version-matched PostgreSQL custom-format backup/restore rehearsal: passed; table catalogs and
  every table row count matched and both disposable databases were removed.
- `git diff --check`: passed.

Provider-consuming AGY/OCR/TTS work and production deployment mutations were not performed.
GitHub/Actions checking was explicitly excluded by the user for this run; no remote-green claim is
made. Every other work-package gate was executed locally.
