# Anatomy of a module

> **Audience:** anyone about to read or change code inside `novelwiki/modules/`.
> This document explains the standard internal structure every business module follows,
> layer by layer, using real code from this repository.

Every module under `novelwiki/modules/<name>/` has the same shape:

```
<name>/
├── __init__.py            # one-line module docstring, nothing else
├── public.py              # the module's cross-module contract (see §1)
├── domain/                # pure rules, prompts, policies          (see §2)
├── application/           # use cases + ports + DTOs               (see §3)
└── adapters/
    ├── inbound/           # HTTP / CLI / worker transports          (see §4)
    └── outbound/          # Postgres / providers / files / bridges  (see §5)
```

The **dependency rule** (the entire point of the structure): source code dependencies only
point *inward*. Concretely, per layer:

| Layer | May import | Must NOT import |
|---|---|---|
| `domain/` | stdlib, `novelwiki.kernel` | anything else — no FastAPI, no asyncpg, no settings, no other modules |
| `application/` | its own `domain/`, `novelwiki.kernel`, other modules' `public.py` **types** | FastAPI, asyncpg, the DB pool, provider SDKs, `novelwiki.platform.database`, any adapter |
| `adapters/inbound/` | its own `application/`, kernel errors, FastAPI/Typer | the database (inbound adapters are **database-free** — verified by the checker), other modules' internals |
| `adapters/outbound/` | its own `application/` ports (to implement them), asyncpg/httpx/etc., `platform.database`, other modules' `public.py` | other modules' internals |
| `public.py` | dataclasses + `typing.Protocol` (+ occasionally its own application contracts re-exported) | anything executable from other modules |

These are not conventions on trust — `tools/check_architecture.py` and
`tests/architecture/test_architecture.py` fail the build on violations
(see [enforcement.md](enforcement.md)).

---

## 1. `public.py` — the cross-module contract

`public.py` is the **only** file another business module (or a workflow) may import from
this module. It contains three kinds of things, all *passive*:

1. **Frozen DTOs** — immutable dataclasses used to pass data across the boundary:

   ```python
   # novelwiki/modules/catalog/public.py
   @dataclass(frozen=True)
   class NovelAccess:
       novel_id: int
       owner_id: int | None
       visibility: str
       contribution_policy: str | None = None
       title: str | None = None
       description: str | None = None
   ```

2. **Capability protocols** — `typing.Protocol` interfaces describing what the module can
   *do* for others. Two flavors:
   - plain capabilities (`CatalogAccess`, `QuotaApi`, `NarrationApi`) that Bootstrap wires
     as pool-backed services, and
   - **transaction APIs** (`CatalogTransactionApi`, `ReadingTranslationTransactionApi`,
     `IdentityQuotaTransactionApi`, …) that can only be obtained *inside a unit of work*
     via `uow.transaction.bind(...)` — this is how cross-module atomicity works
     (see [workflows-and-transactions.md](workflows-and-transactions.md)).

3. **Stable errors/enums** where consumers need them (e.g. AI Execution re-exports
   `AgyError`, `BudgetExhausted`, `Workload`, `ExecutionBackend` through its `public.py`).

What you will **never** find in `public.py`: functions with bodies, SQL, module-level
state, or imports of another module. Importing a protocol tells you *nothing* about who
implements it — that decision belongs to Bootstrap.

Sizes vary with responsibility: Reading's contract is the largest (`reading/public.py`,
~149 lines, seven distinct protocols, because chapters are the shared substrate that
translation, codex, narration, and import all touch), while Experience's is six lines
(`ExperienceQueries` with `home()` and `activity()`).

## 2. `domain/` — pure business rules

Framework-free logic that would survive a rewrite of the web framework, database, and AI
provider. Examples:

- `catalog/domain/policies.py` — who may read/edit a novel given `(owner_id, visibility,
  principal)`; what visibility transitions an admin vs. owner may make.
- `catalog/domain/tags.py` — tag normalization/validation rules.
- `identity/domain/policies.py` — account-status and role rules.
- `acquisition/domain/{document,quality,cleanup}.py` — the block-stream document IR,
  segmentation quality scoring, text cleanup heuristics.
- `narration/domain/textprep.py` — turning chapter text into narratable paragraphs
  (stripping markup, splitting, handling numbers).
- `translation/domain/prompts.py`, `codex/domain/prompts.py` — the LLM prompt templates.
  Prompts are *domain* here deliberately: they encode business rules ("never invent a
  glossary term", "extract only what this chapter establishes") and have no dependency on
  which provider executes them.

Domain code is trivially unit-testable: `tests/unit/` exercises these with no database and
no event loop tricks.

## 3. `application/` — use cases and ports

The heart of a module. Three kinds of files:

### 3a. Ports (`application/ports.py`)

A **port** is a `Protocol` describing something the use case *needs* but doesn't want to
know the details of. Ports are named for the *need*, not the technology. Codex's ports
file is the richest example (`codex/application/ports.py`):

```python
class CeilingPort(Protocol):          # "give me the trusted ceiling for this reader"
    async def resolve(self, novel_id, principal, requested) -> CeilingContext: ...

class CodexAgentPort(Protocol):       # "answer a question / synthesize a profile"
    async def answer(self, novel_id, question, ceiling) -> dict: ...
    ...

class AiCostControlPort(Protocol):    # "guard spend" (verified email, rate, concurrency)
class CatalogEditPort(Protocol):      # "is this principal allowed to edit the novel?"
class BackendResolutionPort(Protocol) # "API or AGY for this user+workload?"
class CodexWorkPort(Protocol):        # "schedule/dedupe a durable job"
class CodexQuotaPort(Protocol):       # "reserve/refund a codex build"
class CodexReadingPort(Protocol):     # "give me chapter text/numbers" (backed by Reading)
```

Note what this achieves: the Codex use case can require *catalog permission checks*,
*identity quota*, and *reading chapter access* without importing any of those modules.
Each port is implemented either by one of Codex's own outbound adapters or by a small
bridge class that Bootstrap builds around another module's public capability.

Several modules also define a `*Runtime` dataclass in ports (e.g. `CodexRuntime`,
`TranslationRuntime`, and Acquisition's `runtime_dependencies.py`): an **immutable bundle
of all capabilities** a command/worker needs, constructed once by Bootstrap and passed
down explicitly (`..., *, runtime`). This is the repo's answer to "no service locators" —
functions receive their dependencies; they never fetch them from globals.

### 3b. Services / commands (the use cases)

Plain classes with injected ports. Examples worth reading:

- `reading/application/services.py::ReadingService` — progress/bookmarks with catalog
  access checks.
- `codex/application/services.py::CodexQueryService` — every spoiler-sensitive read:
  resolves the trusted ceiling first, then delegates to query/agent ports; also the
  cache-then-cost-gates ordering for `ask()` and `recap()`.
- `translation/application/scheduling.py::TranslationSchedulingService` — the
  reserve-quota → resolve-backend → create-or-dedupe-job → refund-on-failure sequence
  (via the `schedule_ai_job` workflow shape).
- `work/application/worker.py::WorkWorkerService` — the state machine for one claimed
  durable job, with all persistence/telemetry behind `WorkWorkerOperations`.
- `narration/application/service.py::NarrationService` — voice resolution, cache
  fast-path, job creation/dedupe for chapter and book scope.
- `experience/application/admin_commands.py::ExperienceAdminCommands` — cross-owner admin
  mutations expressed through consumer-owned ports (`AiAdminPort`, `WorkAdminPort`,
  `AdminAuditPort`).

Application code raises **kernel errors** (`novelwiki/kernel/errors.py`): `NotFound`,
`Forbidden`, `Conflict`, `ValidationFailed`, `InvalidOperation`, `QuotaExceeded`,
`ProviderUnavailable`, `RateLimited(retry_after=…)`, `JobAlreadyActive`. It never raises
`HTTPException` — mapping to transports happens in inbound adapters.

### 3c. DTOs (`application/dto.py`)

Frozen dataclasses used inside/out of the use cases: `reading/application/dto.py`
(`Progress`, `Bookmark`, `ChapterListItem`, `ChapterSnapshot`, `Contribution`),
`codex/application/dto.py` (`CeilingContext` — "the server-trusted reading boundary used
by every spoiler-sensitive use case" — `BackendDecision`, `BuildCodex`), narration's
command objects, etc.

## 4. `adapters/inbound/` — transports that drive the module

Inbound adapters translate an external stimulus into an application call, and application
results/errors back into the transport's language. They are deliberately thin and
**contain no SQL and no pool access**.

- **`http.py`** — a FastAPI `APIRouter` plus Pydantic request models. Two idioms matter:
  1. *Dependency seams:* each router declares placeholder dependency functions
     (`def reading_service_dependency(): ...`) and Bootstrap **overrides** them via
     `app.dependency_overrides[...]` — so the adapter compiles standalone, unit tests can
     inject fakes trivially, and the wiring decision stays in the composition root.
  2. *Error translation:* a small `_raise_http(exc)` maps kernel errors → status codes
     (NotFound→404, Forbidden→403, Conflict/JobAlreadyActive→409, ValidationFailed→422,
     InvalidOperation→400, QuotaExceeded→402/429 per surface, RateLimited→429 with
     `Retry-After`).
- **`cli.py`** — Typer commands (Acquisition, Codex, Translation have them). Same pattern:
  a `configure_*` hook receives command factories from Bootstrap; the Typer function only
  parses arguments and renders output.
- **`worker.py`** — the long-running poll loops for durable jobs (Acquisition's import
  worker, Narration's TTS worker, Work's generic worker, AI Execution's dedicated AGY host
  worker). Each exposes `configure_worker_runtime(runtime)` + `start_worker()`/
  `stop_worker()`; the loop keeps *transport* concerns (polling, leases, heartbeats,
  signal-free shutdown) and delegates every state-machine decision to an application
  service.
- **`jobs.py`** — handlers for the generic Work worker (`execute_scrape_job`,
  `execute_codex_job`, `execute_translation_job`, and their AGY variants). Registered in
  Bootstrap's `WorkerRegistry`; never discovered magically.

## 5. `adapters/outbound/` — implementations of ports

Everything with a real-world side effect:

- **Postgres repositories** — e.g. `reading/adapters/outbound/postgres.py::PostgresReadingRepository`
  ("the sole progress/bookmark SQL writer"), `catalog/.../postgres.py`,
  `identity/.../postgres_{users,sessions,auth,accounts,admin,quota,directory}.py`,
  `codex/.../postgres_queries.py`. Repositories are the *only* place a module's SQL lives,
  and that SQL may only touch tables the module owns (checker-enforced). Two shapes recur:
  - **pool-backed** classes (take the pool; used for ordinary single-module operations),
  - **connection-bound transaction services** (take one `connection`; constructed only by
    the unit-of-work binder for workflow participation), e.g.
    `PostgresReadingTranslationTransactionService`.
- **Provider gateways** — AI Execution's `providers.py` (OpenRouter chat/embed/rerank,
  Gemini vision), the OCR client, narration's `sidecar.py` (OmniVoice HTTP client with the
  shared service token), identity's `oauth.py` (hand-rolled Google/Discord code exchange)
  and `email.py` (aiosmtplib).
- **Filesystem adapters** — identity's `avatars.py`, acquisition's importer `storage.py`,
  codex BM25 index persistence, AGY `workspace.py`.
- **Cross-module bridges** — small classes adapting another module's public capability to
  a port this module defined, e.g. `reading/adapters/outbound/codex.py` (Reading data for
  Codex), `narration/adapters/outbound/migration.py::IdentityNarrationQuota`,
  `translation/adapters/outbound/scheduling.py::{BackendResolutionBridge,
  TranslationWorkBridge, TranslationQuotaBridge}`. Bridges live in the *consumer's*
  outbound folder: the consumer owns its ports.

## 6. Naming conventions cheat-sheet

| Suffix / prefix | Meaning |
|---|---|
| `…TransactionApi` (public.py) | capability only obtainable inside a unit of work via `transaction.bind` |
| `…TransactionService` (outbound) | connection-bound implementation of the above |
| `…Port` (application/ports.py) | something this module needs, to be injected |
| `…Bridge` (outbound) | adapter from another module's public capability to a local port |
| `…Runtime` | immutable bundle of injected capabilities for commands/workers |
| `build_…` (bootstrap) | composition function that constructs and wires a service |
| `…_dependency` (inbound http) | FastAPI dependency seam overridden by Bootstrap |
| `configure_…` (inbound) | one-time injection hook called by Bootstrap before serving |

## 7. How to add things without breaking the architecture

**A new endpoint in an existing module** — add the Pydantic model + handler to the
module's `adapters/inbound/http.py`, put the logic in an application service, extend a
port + outbound adapter if new data is needed. Then regenerate the contract snapshots
(routes/OpenAPI changed): see [enforcement.md](enforcement.md).

**A new capability another module needs from you** — add a `Protocol` + DTOs to your
`public.py`, implement it in your outbound layer, and have Bootstrap inject it into the
consumer's port. Never let the consumer import your internals.

**A new cross-module atomic write** — a new named workflow (see
[workflows-and-transactions.md](workflows-and-transactions.md)) plus `…TransactionApi`
entries in each participating module's `public.py` and transaction-bound services in their
outbound layers, registered in the UoW factory Bootstrap builds.

**A whole new module** — mirror the layout above, add your tables to the ownership
registry (`implementation-plan/modular-monolith-clean-architecture-migration-plan.md` +
`docs/architecture/module-ownership.md`), give the checker your module name, and wire it
in Bootstrap. Expect `tools/check_architecture.py` to be your reviewer.
