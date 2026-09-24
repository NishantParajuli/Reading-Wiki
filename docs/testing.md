# Testing Tideglass

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

Unit, architecture, and contract-snapshot tests do not require PostgreSQL:

```bash
uv run pytest -q tests
```

Website extraction fixtures live under `tests/unit/modules/acquisition/`: existing
adapters, new translation sites, Novelpia/RAW archives, runner resume/error handling,
and the diagnostic CLI. They use synthetic text and do not make live website requests.
For a bounded check against an actual website without importing its text or requiring
PostgreSQL, use `uv run python try_adapter.py ADAPTER URL --max 2`. See
[supported sites](pipelines/supported-sites.md#check-a-source-without-importing-it) for
accepted URLs, archive-password input, exit codes, and the scope of live verification.

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

OpenAI Codex App Server tests use a fake JSONL subprocess and host-side artifact
materialization, so the normal suite consumes no ChatGPT capacity. The authenticated
preflight is also non-consuming: it verifies the pinned CLI, initializes App Server,
checks `account/read`, and lists configured models without starting a turn:

```bash
uv run python -m novelwiki.modules.ai_execution.adapters.outbound.openai_codex.preflight
```

The admin OpenAI Codex smoke action is intentionally separate because it starts a real,
rate-limited model turn. Run it once during rollout, then qualify representative translation
and extraction chapters before enabling either global switch for general use; see the
[OpenAI Codex operator runbook](openai-codex-operator-runbook.md).

`agy_workload_tests.py::test_chapter_1200_context_stays_bounded_and_ignores_historical_fact_bloat`
is the provider-free long-book qualification. It creates a synthetic LOTM-shaped chapter/volume
layout, 500 entities, temporal state, threads, and more than 20,000 historical facts in the
disposable database; then it proves chapter 1,200 context is deterministic, ceiling-safe, and
within every configured entity/section/total budget. Run with `-s` to print the measured context
tokens, selected/dropped entity counts, and packing time.

## Provider qualification history

The [historical Codex qualification record](testing-codex-qualification-history.md)
preserves dated canaries and test counts. Those measurements are evidence for their
recorded versions; rerun the current gates below for a new release.

## Read-side grounding regression gates

`tests/unit/codex/test_read_side_grounding.py` is provider-free and exercises the interactive
quality boundary: hybrid retrieval automatically invokes reranking but retains fused candidates
when that provider is unavailable; question/profile citations must belong to supplied evidence;
Ask verifier failure cannot publish or cache an unchecked draft; deterministic findings force a
repair; and profile/model/grounding cache namespaces invalidate older generated prose. The broader
disposable-database spoiler and cost-control suites continue to cover trusted ceilings, cache-hit
ordering, concurrency cleanup, and tool clamps. These tests establish host behavior; representative
real-model questions across early, middle, late, negative-answer, identity-reveal, and obscure-detail
cases remain a release qualification rather than something inferred from unit tests.

## Complete local release checks

Install Python dependencies with `uv sync --frozen`. Frontend and browser checks also
need the locked npm dependencies and Chromium; the sequence below includes that setup.
Use a test-only PostgreSQL/pgvector instance. In addition to the random databases used
by pytest and the real-browser launcher, initialize the benchmark database named in
`TEST_DATABASE_URL` with the schema command below. The benchmark uses only the explicit
`--database-url` for its connections; it does not derive database access from app settings.

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
npm ci
npx playwright install chromium  # use --with-deps on Linux CI to install OS libraries too
npm test
npm run build
npm run test:e2e
cd ../..
uv run python scripts/test_real_browser.py
```

The query benchmark checks query-plan costs, transactional worker-claim throughput, and
successful ASGI latency for `/health` and authenticated `/api/discover`. Discover uses a
temporary reader/session and one searchable shared novel with a chapter; it includes the
real session lookup, filtered Discover SQL, middleware, and serialization. Every sample
must return HTTP 200 and the expected response data, including that novel's chapter count.
The fixture is removed and the benchmark pool closed on success or failure. It deliberately
does not start the application lifespan, workers, or providers. These are regression budgets
for a small synthetic fixture, not representative production-scale load measurements; the
historical performance baseline remains unchanged.

The architecture checker enforces table writers/readers, an acyclic module graph, SQL-free inbound
adapters, removal of the frontend API facade, cross-module frontend import surfaces, and reviewed
screen-size limits. PostgreSQL integration tests cover locks, claims, quota races, offset renumbering,
import replacement, single- and batch-volume appends, concurrent automatic volume range allocation,
overlay conflicts, audio indexes, and spoiler ceilings. The PDF import suite also covers
cross-page paragraph rejoining, decorative-image
filtering, inferred and bare-filename volume metadata, and cover selection. Focused application
and frontend tests cover user metadata precedence, multi-file queueing, and manual series/volume
review controls. Narration timing unit tests cover sidecar duration capture, manifest validation,
sentence mapping within real paragraph boundaries, and the untimed legacy-audio fallback.
The mocked Playwright scenarios in `novelwiki/frontend/e2e/critical-paths.spec.js`
cover critical flows with fetch-level fixtures, including mobile narration highlighting
and automatic reveal. List the current cases with `npm run test:e2e -- --list` from
`novelwiki/frontend`; counts change as regressions are added. The regular browser run
skips `real-backend.spec.js` unless `REAL_BACKEND=1`.

`scripts/test_real_browser.py` creates its own random `tg_playwright_*` database and
temporary file roots, starts FastAPI on port 8011, and runs the real-stack browser path
through Vite on port 4173. Stop any existing Vite server on 4173 first: Playwright reuses
an existing server outside CI, which could otherwise retain a different API proxy. Set
both `TEST_*` database URLs explicitly as above: the launcher refuses to start without
them and never derives test authority from application database settings. Database
connections have a five-second timeout. Its child app clears provider API keys and
SMTP configuration and disables AGY, OpenAI Codex, and new TTS generation; the browser
qualification uses cached/provider-free fixtures, including ordinary imports and cached
audio, without using production provider credentials.

## Backup and restore rehearsal

To rehearse a backup and restore using two hard-coded disposable databases:

```bash
TEST_DB_SUPERUSER_URL=postgresql://.../postgres scripts/rehearse-backup-restore.sh
```

The client image defaults to PostgreSQL 18. Set
`POSTGRES_CLIENT_IMAGE=postgres:<server-major>-alpine` when rehearsing against another supported
server major so dump and restore tooling match the target.

The script refuses non-`novelwiki_rehearsal_*` database names, verifies the restored table catalog
and every table's row count, and cleans up both databases even after a failure.
