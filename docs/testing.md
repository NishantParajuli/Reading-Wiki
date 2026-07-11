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
