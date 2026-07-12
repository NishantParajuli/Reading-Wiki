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
import replacement, overlay conflicts, audio indexes, and spoiler ceilings. Playwright covers ten
critical browser paths with fetch-level fixtures.

To rehearse a backup and restore using two hard-coded disposable databases:

```bash
TEST_DB_SUPERUSER_URL=postgresql://.../postgres scripts/rehearse-backup-restore.sh
```

The client image defaults to PostgreSQL 18. Set
`POSTGRES_CLIENT_IMAGE=postgres:<server-major>-alpine` when rehearsing against another supported
server major so dump and restore tooling match the target.

The script refuses non-`novelwiki_rehearsal_*` database names, verifies the restored table catalog
and every table's row count, and cleans up both databases even after a failure.
