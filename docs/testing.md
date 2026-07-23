# Testing NovelWiki

Backend integration tests create a random `tg_pytest_*` database and destroy it after
the run. They never use the configured application database directly. The launcher
deliberately refuses to infer destructive-test authority from the app's `DATABASE_URL`:
point both variables at a PostgreSQL/pgvector server on which the test user may create
and drop databases. The named app database is only a naming/connection template.

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/novelwiki \
TEST_DB_SUPERUSER_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  uv run python scripts/test_backend.py
```

The launcher maps Docker's `host.docker.internal` to `127.0.0.1` when tests run on
the host. Connections fail within five seconds and diagnostics contain only the host and
database name, never credentials.

Architecture-only tests do not require PostgreSQL:

```bash
uv run pytest -q tests
```

AGY contract/runner/workload suites use `novelwiki/eval/fake_agy.py` and do not consume
subscription capacity. The authenticated CLI canary is opt-in because it makes real model
requests:

```bash
export TEST_DATABASE_URL=postgresql://test-user:password@127.0.0.1:5432/novelwiki_test
export TEST_DB_SUPERUSER_URL=postgresql://test-admin:password@127.0.0.1:5432/postgres
RUN_REAL_AGY_TESTS=1 uv run pytest -q novelwiki/eval/agy_real_cli_tests.py -m agy_real
```

For the pinned AGY 1.1.2 binary, the canary requires a completed `READY` artifact, a manifest
finalized by the trusted stop hook, both loaded safety hooks, and bounded model requests. The
runner tests separately prove that planner/tool steps with output progress are allowed while a
no-progress loop is killed. A non-committing real-data Codex canary is available with repeated
chapter flags sharing one preflight:

```bash
uv run python scripts/diagnose_agy_codex.py --novel-id 33 \
  --chapter 1 --chapter 2 --chapter 3 --chapter 4 --chapter 5
```

Keep the default-off Codex kill switch until representative chapters pass on the exact pinned
binary/plugin pair and the operator intentionally enables rollout.

`agy_workload_tests.py::test_chapter_1200_context_stays_bounded_and_ignores_historical_fact_bloat`
is the provider-free long-book qualification. It creates a synthetic LOTM-shaped chapter/volume
layout, 500 entities, temporal state, threads, and more than 20,000 historical facts in the
disposable database; then it proves chapter 1,200 context is deterministic, ceiling-safe, and
within every configured entity/section/total budget. Run with `-s` to print the measured context
tokens, selected/dropped entity counts, and packing time.

### Dated Codex v2 provider qualification (2026-07-16)

These paid canaries used real Lord of the Mysteries chapter 1 in disposable databases; production
was read-only and the disposable databases were removed afterward.

- Direct API (`deepseek/deepseek-v4-flash`) completed extraction, verification, and the
  grounded chapter summary in exactly three chat calls. The committed proposal had valid
  source/context hashes and provenance; rerunning the completed chapter made no provider call.
- One real `perplexity/pplx-embed-v1-0.6b` smoke call returned a normalized 1,024-dimensional
  vector.
- AGY plugin `1.3.1` (`Gemini 3.5 Flash (High)`) completed a real chapter-1 v2 run under an
  eight-request ceiling: trusted artifact validation passed, the proposal committed atomically,
  and the run persisted `completed`. A disposable diagnostic wrapper then failed while formatting
  a nonexistent reporting-only preflight field; this occurred after application completion and was
  not rerun to avoid unnecessary paid usage.

This evidence qualifies the early chapter path, shared commit contract, and bounded context. It
does **not** claim that late, checkpoint-end, or final-volume AGY canaries have passed; those remain
explicit production rollout gates in the
[AGY operator runbook](agy-operator-runbook.md#codex-v2-rollout).

The blocking local release-candidate checks are:

```bash
export TEST_DATABASE_URL=postgresql://test-user:password@127.0.0.1:5432/novelwiki_test
export TEST_DB_SUPERUSER_URL=postgresql://test-admin:password@127.0.0.1:5432/postgres

uv run python tools/check_architecture.py --strict
uv run pytest -q tests
uv run python scripts/contracts.py
uv run python scripts/test_backend.py
DATABASE_URL="$TEST_DATABASE_URL" DB_SUPERUSER_URL="$TEST_DB_SUPERUSER_URL" \
  uv run python -m novelwiki.db.schema
uv run python tools/benchmark_queries.py --database-url "$TEST_DATABASE_URL" --check
cd novelwiki/frontend
npm test
npm run build
npm run test:e2e
cd ../..
uv run python scripts/test_real_browser.py
```

The architecture checker enforces table writers/readers, an acyclic module graph, SQL-free inbound
adapters, removal of the frontend API facade, cross-module frontend import surfaces, and reviewed
screen-size limits. PostgreSQL integration tests cover locks, claims, quota races, offset renumbering,
import replacement, single- and batch-volume appends, overlay conflicts, audio indexes, and spoiler
ceilings. The PDF import suite also covers cross-page paragraph rejoining, decorative-image
filtering, inferred and bare-filename volume metadata, and cover selection. Focused application
and frontend tests cover user metadata precedence, multi-file queueing, and manual series/volume
review controls. Playwright covers ten critical browser paths with fetch-level fixtures.

To rehearse a backup and restore using two hard-coded disposable databases:

```bash
TEST_DB_SUPERUSER_URL=postgresql://.../postgres scripts/rehearse-backup-restore.sh
```

The client image defaults to PostgreSQL 18. Set
`POSTGRES_CLIENT_IMAGE=postgres:<server-major>-alpine` when rehearsing against another supported
server major so dump and restore tooling match the target.

The script refuses non-`novelwiki_rehearsal_*` database names, verifies the restored table catalog
and every table's row count, and cleans up both databases even after a failure.
