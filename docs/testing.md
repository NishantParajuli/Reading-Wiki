# Testing NovelWiki

Backend integration tests create a random `tg_pytest_*` database and destroy it after the run.
They never use the configured application database directly.

```bash
uv run python scripts/test_backend.py
```

The launcher maps Docker's `host.docker.internal` to `127.0.0.1` when tests run on the host. In CI,
set `TEST_DATABASE_URL` and `TEST_DB_SUPERUSER_URL` explicitly to a PostgreSQL service containing
the pgvector extension. Connections fail within five seconds and diagnostics contain only the
host and database name, never credentials.

Architecture-only tests do not require PostgreSQL:

```bash
uv run pytest -q tests
```

The blocking local release-candidate checks are:

```bash
uv run python tools/check_architecture.py
TEST_DATABASE_URL=... TEST_DB_SUPERUSER_URL=... uv run pytest -q
uv run python tools/benchmark_queries.py --database-url "$TEST_DATABASE_URL" --check
cd novelwiki/frontend
npm test
npm run build
npm run test:e2e
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

The script refuses non-`novelwiki_rehearsal_*` database names, verifies the restored table catalog
and every table's row count, and cleans up both databases even after a failure.
