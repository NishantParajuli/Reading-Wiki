# How the architecture is enforced

> **Audience:** anyone making changes. This explains every automated gate that will fail
> your change if it breaks a boundary or an external contract, and what to do when one
> fires.

The migration's central promise is that boundaries are **mechanically enforced**, not
tribal knowledge. Three layers of enforcement exist: architecture checks, contract
snapshots, and the ordinary test suites.

## 1. Architecture checks

```bash
uv run python tools/check_architecture.py            # boundary rules
uv run python tools/check_architecture.py --strict   # + layer & public-surface audits
uv run pytest -q tests/architecture                  # same rules as a pytest suite
```

No PostgreSQL needed — these are static analyses over the production tree
(implemented in `novelwiki/platform/architecture/checks.py`). What each rule catches:

| Rule | Fails when… | Fix by… |
|---|---|---|
| **Table ownership** | any module's SQL writes a table it doesn't own, or reads across owners outside a registered Experience projection / approved surface | moving the SQL into the owner's outbound adapter and exposing a capability, or registering a reviewed read-only projection in Experience |
| **Module cycles** | the executable cross-module import graph (alias-aware) gains a cycle | inverting one edge with a consumer-owned port + Bootstrap injection |
| **Cross-module imports** | `modules/A/**` imports anything from `modules/B/**` other than `public.py` | importing the type from `public.py`, or injecting the capability |
| **Legacy facade imports** | a business module imports a compatibility path (`novelwiki.auth.*`, `novelwiki.jobs.*`, `novelwiki.quota`, …) | using the canonical module/platform path; facades are for external consumers only |
| **Inbound database ban** | SQL strings or pool usage appear in any `adapters/inbound/` file (HTTP/CLI/worker transports are database-free) | pushing persistence into the application/outbound layers |
| **Pool placement** | pool initialization occurs outside outbound adapters/Bootstrap | letting Bootstrap construct pool-backed services |
| **Frontend boundaries** | the deleted global API/query facade returns, a slice imports another slice's implementation file, or a reviewed route screen exceeds its size limit | using the owning slice's public `api.js`/`queries.js`/`index.js`, shared hooks, or extracting components |
| **Layer matrix / public surface** (strict) | domain importing application, application importing adapters, non-passive `public.py`, etc. | restructuring per [module-anatomy.md](module-anatomy.md) |

There is no suppression count and no baseline file: **any** violation ⇒ exit 1. A genuine
exception requires a dated ADR naming an owner and a removal condition, plus a
checker suppression that names that ADR (per [ADR 001](adr-001-modular-monolith.md)).
The historical burn-down (10 owner-SQL, 2 pool, 199 facade-import violations → 0) is
recorded in [architecture-debt.md](architecture-debt.md).

## 2. Contract snapshots (`tests/contracts/`)

The migration froze the externally observable surface. `tests/contracts/test_snapshots.py`
compares the live application against deterministic JSON snapshots in
`tests/contracts/snapshots/`:

| Snapshot | Freezes |
|---|---|
| `routes.json` | the full HTTP route inventory (method + path + endpoint name; currently 119 routes) |
| `openapi.json` | the normalized OpenAPI document (request/response schemas) |
| `cli.json`, `cli_help.json` | the 13 CLI commands and every help surface, captured semantically via Typer's `CliRunner` (ANSI styling/wrapping discarded; every word, option, default, and command order kept) |
| `schema.json` | normalized DDL (which creates all 39 tables) plus the 38-entry `ALL_TABLES` reset list; `auth_rate_limits` omission is frozen by ADR 002 |
| `job_states.json` | the three job systems' state machines (generic kinds + active/terminal sets, import trigger/marker/resume map, TTS states) |
| `responses.json` | representative success/error JSON for every route family |
| `agy_contracts.json` | AGY manifest schemas and plugin file hashes |
| `frontend_inventory.json` | frontend routes and the per-module endpoint lists |

If your change *intentionally* alters a contract (new endpoint, new column, new CLI
option), regenerate via `uv run python scripts/contracts.py --update` and commit the diff — the snapshot diff *is*
the reviewable statement of the external change. If the diff surprises you, the change
was not intentional. `docs/architecture/migration-equivalence-final.md` records the
SHA-256s proving the migrated tree matched the pre-migration baseline.

## 3. Test suites

Full instructions in [../testing.md](../testing.md); summary of who tests what:

| Suite | Command | Needs PG? | Covers |
|---|---|---|---|
| Unit | `uv run pytest -q tests/unit` | no | domain policies, application services with fake ports, kernel/platform pieces, workflow logic |
| Architecture | `uv run pytest -q tests/architecture` | no | §1 rules |
| Contracts | `uv run pytest -q tests/contracts` | no | §2 snapshots |
| Backend integration (eval) | `TEST_DATABASE_URL=… TEST_DB_SUPERUSER_URL=… uv run python scripts/test_backend.py` | yes (creates a disposable `tg_pytest_*` DB, needs pgvector) | end-to-end suites in `novelwiki/eval/`: auth/CSRF security, spoiler boundaries, durable jobs, import (incl. chunked upload attack cases), scraper SSRF, sidecar auth, quota/cost controls, AGY policy/runner/workload contracts, product smoke |
| Frontend | `cd novelwiki/frontend && npm test && npm run build && npm run test:e2e` | – | component/API-contract unit tests, production build, Playwright critical paths |
| Query performance | `uv run python tools/benchmark_queries.py --database-url "$TEST_DATABASE_URL" --check` | yes | hot-path query plans/latencies vs. `docs/architecture/performance-baseline.json` |

The blocking local release-candidate sequence (also in [../testing.md](../testing.md)):
checker → full pytest with a test DB → query benchmark → frontend test/build/e2e.

## 4. Pre-merge checklist

1. `uv run python tools/check_architecture.py` — must print `architecture boundaries: ok`.
2. `uv run pytest -q tests` — architecture + contracts + unit, no DB required.
3. If you touched routes/CLI/schema/job states: regenerate snapshots, review the diff.
4. If you touched behavior with runtime surface: run the eval suite against a test DB.
5. If you touched the frontend: `npm test && npm run build`.
6. New cross-module write? It must be a named workflow —
   [workflows-and-transactions.md](workflows-and-transactions.md) — and appear in
   [module-ownership.md](module-ownership.md).
7. New table? Assign a single writer in the ownership registry, or the checker will not
   know who owns it.
8. New exception to a rule? Dated ADR + owner + removal condition, or it doesn't merge.
