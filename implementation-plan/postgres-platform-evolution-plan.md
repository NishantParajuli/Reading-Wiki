# PostgreSQL-centered platform evolution plan

> **Status:** proposed future work — none of the behavior in this document should be
> assumed to exist until the corresponding implementation, tests, contract snapshots,
> and living documentation land together.
>
> **Written:** 2026-07-14
>
> **Purpose:** preserve the reasoning and implementation detail behind a possible
> evolution of Tideglass into a more operationally mature, PostgreSQL-centered system.
> This is a plan and learning roadmap, not a living description of `HEAD`.

## 1. Executive summary

Tideglass already uses PostgreSQL as much more than a relational data store. It is the
system of record, vector database, durable counter/lock store, cache store, and backing
store for three job queues. That is a good fit for the current product and deployment.
There is no immediate need to add MongoDB, Redis, RabbitMQ, Kafka, or a dedicated vector
database.

The next useful evolution is not “add more infrastructure products.” It is to make the
existing PostgreSQL-centered design more explicit, safer to operate, and more educational:

1. enforce the existing single-TTS-worker assumption with a database singleton lock;
2. separate HTTP and worker process roles while continuing to ship one image;
3. replace startup-time idempotent DDL with versioned, checksummed migrations;
4. inventory and reconcile the filesystem artifacts referenced by PostgreSQL;
5. add a durable transactional event bus whose rows are authoritative and whose
   `LISTEN/NOTIFY` notifications are only wake-up hints;
6. make AI cache identity, invalidation, retention, and stampede behavior explicit;
7. add failed-work redrive, queue controls, attempt history, and useful operator views;
8. add metrics, fault-injection tests, and a coordinated database/filesystem recovery
   procedure.

The important architectural distinction is:

| Mechanism | Meaning | Delivery expectation |
|---|---|---|
| Durable job | “One worker must perform this command.” | one successful consumer |
| Durable event | “This fact happened; every registered consumer may react.” | one delivery per consumer |
| PostgreSQL notification | “Wake up; durable rows may now be available.” | lossy hint; never authoritative |

The existing `jobs`, `import_jobs`, and `tts_jobs` tables remain job queues. The proposed
event bus supplements them; it does not replace them.

## 2. Current baseline and constraints

Read these living references before implementing any phase:

- [database schema](../docs/data/database-schema.md)
- [background jobs and quota](../docs/pipelines/background-jobs-and-quota.md)
- [filesystem layout](../docs/data/filesystem-layout.md)
- [composition root](../docs/architecture/composition-root.md)
- [workflows and transactions](../docs/architecture/workflows-and-transactions.md)
- [module ownership](../docs/architecture/module-ownership.md)
- [deployment](../docs/operations/deployment.md)
- [release and rollback](../docs/release-runbook.md)

### 2.1 Runtime shape at the time this plan was written

- One FastAPI/uvicorn web process starts the import, narration, and generic Work worker
  loops from `novelwiki/bootstrap/lifecycle.py`.
- The generic Work and Import queues use atomic `FOR UPDATE SKIP LOCKED` claims, claim
  tokens, heartbeats, stale-lease recovery, retries, and cooperative cancellation. They
  are safe with more than one worker process.
- Narration uses a deliberately single-instance worker. It requeues every
  `generating` TTS job at startup and relies on per-audio-target PostgreSQL advisory
  locks for idempotent generation. The target lock does not make startup recovery safe
  when two TTS workers exist.
- The dedicated AGY worker is already a separate host process and records heartbeats in
  PostgreSQL.
- All workers poll for work, normally every two seconds. There are no `LISTEN` or
  `NOTIFY` code paths.
- PostgreSQL owns durable state and artifact manifests. Large bytes remain on the
  filesystem: BM25 indexes, images, audio, import artifacts, and AGY workspaces.
- `query_cache` and `wiki_cache` are invalidated by application code. They have creation
  timestamps, but no expiry, size bound, access tracking, or complete code/model/prompt
  identity in their keys.
- The schema is applied at startup as idempotent DDL from `novelwiki/db/schema.py`.
  One guarded data migration uses the `app_migrations` marker table.

### 2.2 Dated deployment observation

The following is context, not a permanent promise. A read-only inspection on
2026-07-13 observed:

- PostgreSQL 18.4 with `vector` 0.8.2 and `pg_trgm` 1.6;
- 39 application tables and roughly 216 MiB of database relations;
- 8,761 `chunks`, all with embeddings and an active HNSW cosine index;
- approximately 1.1 GiB of audio and 66 MiB of assets outside PostgreSQL;
- no Redis, RabbitMQ, MongoDB, Kafka, or separate vector database dependency.

These numbers explain the priorities. Queue polling and vector scale are not current
bottlenecks. Filesystem integrity, worker topology, migration discipline, and recovery
are more valuable than prematurely adding distributed infrastructure.

### 2.3 Repository rules this plan must preserve

Every implementation phase must honor the existing architecture:

- A table has one writer module, recorded in
  `novelwiki/platform/architecture/checks.py::TABLE_OWNERS` and
  `docs/architecture/module-ownership.md`.
- Inbound HTTP, CLI, and worker adapters do not use SQL or the database pool.
- Cross-module writes happen through named workflows and transaction-bound public
  capabilities.
- Bootstrap performs wiring and registry construction; feature modules do not import
  each other's internals.
- Correctness-critical changes that must be atomic stay in one PostgreSQL transaction.
- Filesystem and provider side effects happen after commit and must be retryable and
  idempotent.
- Behavior, schema, job states, CLI, routes, and other external contracts are snapshot
  tested. Intentional changes require snapshot regeneration and review.
- Living documentation must describe implemented behavior, not this plan. Update it in
  the same change that implements a phase.

## 3. Goals, non-goals, and design principles

### 3.1 Goals

- Preserve PostgreSQL as the durable source of truth and coordination mechanism.
- Allow HTTP and worker processes to start, stop, and scale independently.
- Make the single-TTS-worker restriction enforced rather than conventional.
- Gain immediate worker wakeups without sacrificing durable polling recovery.
- Support durable event fan-out, independent retries, dead letters, and replay.
- Make every external side effect safe under duplicate delivery.
- Make schema changes reviewable, ordered, reproducible, and safe on existing data.
- Detect and repair divergence between database manifests and filesystem artifacts.
- Prevent stale AI answers after content, prompt, model, or retrieval changes.
- Give operators enough visibility to understand and recover stuck work.
- Build fault-injection and recovery knowledge without adding unnecessary services.

### 3.2 Non-goals

- Reimplement all RabbitMQ, Kafka, Redis, or Temporal features.
- Guarantee exactly-once execution of arbitrary filesystem, email, HTTP, or model calls.
- Put large audio, image, PDF, EPUB, or BM25 bytes into PostgreSQL merely to claim that
  PostgreSQL stores everything.
- Horizontally scale TTS before more than one GPU/sidecar exists.
- Move permission checks, quota settlement, spoiler boundaries, or content commits into
  eventually consistent consumers.
- Add table partitioning, read replicas, sharding, or Kubernetes without measured need.
- Replace the current BM25 implementation without a quality and latency benchmark.

### 3.3 Principles

1. **Rows are truth; notifications are hints.** Missing a notification may add latency,
   but must never lose a job or event.
2. **At-least-once plus idempotency.** Any consumer may run more than once. A duplicate
   must converge on the same final state.
3. **Emit facts atomically.** When an event describes a committed database fact, insert
   its outbox row in the same transaction as that fact.
4. **Keep invariants synchronous.** Eventual work is for cleanup, projections,
   notifications, derivative artifacts, and follow-up commands.
5. **Prefer deterministic identities.** Event IDs, content versions, cache generations,
   file hashes, and idempotency keys make retries understandable.
6. **Separate lifecycle from business behavior.** Process roles own polling, signals,
   health, and shutdown; application services own state-machine decisions.
7. **Build observability with the mechanism.** A queue or event bus without age,
   failure, retry, and lease visibility is unfinished.
8. **Roll out in reversible increments.** Compatibility releases should precede changes
   that alter deployment topology or schema ownership.

## 4. Target architecture

```text
                         ┌──────────────────────────┐
                         │ PostgreSQL               │
                         │                          │
 HTTP requests ─────────▶│ domain state             │
                         │ durable jobs             │
                         │ outbox + deliveries      │
                         │ caches + vector indexes  │
                         │ leases + singleton locks │
                         └──────┬───────────┬───────┘
                                │ rows      │ NOTIFY hints
                 ┌──────────────┼───────────┼────────────────┐
                 ▼              ▼           ▼                ▼
          generic worker   import worker  event worker   TTS worker
                                                              │
                                                              ▼
                                                        GPU TTS sidecar

                         ┌──────────────────────────┐
                         │ Persistent filesystem    │
                         │ assets / audio / imports │
                         │ BM25 / AGY workspaces    │
                         └────────────┬─────────────┘
                                      │
                               reconciler +
                              cleanup consumers
```

One container image may provide all entrypoints, but production Compose should run
explicit roles. A convenient all-in-one mode may remain for local development.

## 5. Recommended delivery sequence

The estimates are rough engineering time for one person who knows the repository. They
include focused tests and documentation, but not waiting time for production observation.

| Phase | Deliverable | Estimate | Depends on |
|---|---|---:|---|
| 0 | Baselines, decisions, and failure tests | 1–2 days | — |
| 1 | Enforced singleton TTS worker | 0.5–1 day | phase 0 |
| 2 | Separate web/worker process roles | 2–4 days | phase 1 |
| 3 | Versioned migration runner and baseline | 4–8 days | phase 0 |
| 4 | Report-only storage reconciler | 2–4 days | phase 3 if schema changes |
| 5 | Durable outbox, fan-out deliveries, `NOTIFY`, DLQ, first event | 7–14 days | phases 2–3 |
| 6 | Cache generation, code identity, retention, stampede control | 3–6 days | phase 3 |
| 7 | Queue redrive, attempt history, controls, optional priority | 3–6 days | phases 2–3 |
| 8 | Metrics, health, correlation, fault injection | 3–7 days | incremental throughout |
| 9 | Coordinated backup/restore and repair rehearsal | 3–6 days | phases 4–8 |

Do not implement the entire table as one PR. Each phase should leave production in a
working, documented, rollback-capable state.

## 6. Phase 0 — baseline and decisions

### 6.1 Why this phase exists

Concurrency, migrations, and delivery guarantees are easy to describe imprecisely. Lock
down the current behavior and the intended semantics before changing topology.

### 6.2 Work

1. Record queue baselines:
   - claim latency;
   - queue depth and oldest-job age;
   - typical and maximum job duration by kind;
   - retry/failure counts;
   - database query rate produced by idle polling.
2. Record storage baselines by root and artifact kind.
3. Add or confirm tests for:
   - two generic workers claiming distinct jobs;
   - stale generic/import lease recovery;
   - TTS restart requeue behavior;
   - quota finalization under failure and cancellation;
   - missing audio file behavior;
   - cache invalidation after content changes.
4. Decide and record:
   - event persistence owner: **recommended: Work**, because Work already owns durable
     asynchronous execution and worker state;
   - worker entrypoint names;
   - migration file format and runner;
   - event retention duration;
   - whether local development defaults to an all-in-one process.
5. Add an ADR when accepting a durable architectural decision, especially event
   delivery semantics or the migration strategy. This plan itself is not an ADR.

### 6.3 Exit criteria

- Baseline commands are reproducible.
- Existing failure semantics are covered by tests.
- Table ownership and process-role decisions are explicit.
- No user-visible behavior has changed.

## 7. Phase 1 — enforce one TTS worker

### 7.1 Why

One TTS worker is appropriate while one heavy GPU sidecar exists. The problem is not the
single-worker design; the problem is that it is currently an unenforced deployment
assumption. Two web processes would each start a TTS loop, and the second process could
requeue a job actively generated by the first.

### 7.2 Design

Use a session-level PostgreSQL advisory lock held on a dedicated connection for the
worker's entire lifetime.

Pseudo-flow:

```python
connection = await pool.acquire()
leader = await connection.fetchval(
    "SELECT pg_try_advisory_lock(hashtext($1), hashtext($2))",
    "novelwiki-worker", "tts",
)
if not leader:
    report_standby()
    release(connection)
    return

try:
    requeue_interrupted_tts_jobs()  # only the elected leader may do this
    run_tts_loop()
finally:
    pg_advisory_unlock(...)
    release(connection)
```

Requirements:

- Acquire the singleton lock **before** `generating → queued` startup recovery.
- Do not use a transaction-scoped lock; it would release at commit.
- Keep the lock connection separate from ordinary query acquisitions.
- If the connection holding the lock is lost, stop claiming/processing work. PostgreSQL
  has released the lock, so another process may become leader.
- Expose `leader`, `standby`, `stopping`, and `unhealthy` status in logs/health data.
- Use a stable two-part lock namespace to avoid accidental collision with target locks.
- Continue using the existing per-audio-target advisory lock. The singleton protects
  worker lifecycle; the target lock protects artifact idempotency.

### 7.3 Configuration

Add an explicit switch such as `TTS_WORKER_ENABLED`. Avoid inferring worker intent only
from whether the TTS sidecar URL is configured. A valid deployment may expose cached
audio while intentionally running no generator.

### 7.4 Tests

- Two contenders against one database: exactly one becomes leader.
- The standby does not requeue `generating` rows.
- Releasing or losing the leader connection allows the standby to acquire leadership.
- Shutdown releases leadership after the worker stops.
- Existing single-worker narration and cache tests still pass.

### 7.5 Future multi-GPU path

Do not add it now. If more than one TTS sidecar is eventually required, replace startup
requeue with the generic claim/lease model:

- `claim_token`, `claimed_at`, heartbeat, attempts, `max_attempts`;
- stale-lease recovery rather than requeue-all-on-start;
- worker/sidecar capability routing;
- bounded concurrency per GPU;
- target locks retained as the last idempotency barrier.

## 8. Phase 2 — separate process roles

### 8.1 Desired roles

Use one application image with separate commands:

| Role | Responsibility |
|---|---|
| `web` | HTTP, SPA, auth, request-scoped inline work; no durable polling loops |
| `work-worker` | generic API-backed `jobs` kinds |
| `import-worker` | `import_jobs` pipeline |
| `tts-worker` | singleton `tts_jobs` consumer and TTS sidecar client |
| `event-worker` | proposed outbox fan-out and event deliveries |
| `agy-worker` | existing dedicated host worker |

Exact module/CLI names are an implementation choice. Prefer stable Python entrypoints
that Bootstrap composes. Do not duplicate dependency wiring inside Docker Compose shell
commands.

### 8.2 Composition changes

- Refactor `build_application_lifecycle()` into reusable hook groups or role-specific
  lifecycle builders.
- Keep database pool initialization and ordered shutdown common.
- Web startup may validate schema/migration state but must not run worker recovery.
- Each worker role wires only the handlers and gateways it uses.
- Preserve a documented `all` role for local development if it materially improves the
  developer experience.
- Ensure signal handling stops claims, allows bounded in-flight completion, then closes
  the pool.
- Keep the current standalone import-worker command compatible or intentionally migrate
  it with contract updates.

### 8.3 Compose/deployment shape

Add services using the same image and persistent volume:

```yaml
services:
  web:
    image: wiki-web:latest
    command: ["uvicorn", "novelwiki.api.app:app"]

  work-worker:
    image: wiki-web:latest
    command: ["python", "-m", "<work-worker-entrypoint>"]

  import-worker:
    image: wiki-web:latest
    command: ["python", "-m", "<import-worker-entrypoint>"]

  tts-worker:
    image: wiki-web:latest
    command: ["python", "-m", "<tts-worker-entrypoint>"]
```

The web and workers all need database access. Roles that read/write artifact files must
mount the same persistent volume. Only `web` publishes an HTTP port. TTS/OCR sidecars
remain private.

### 8.4 Rollout

Use a two-release transition:

1. Release A introduces standalone roles and feature switches while retaining the
   existing all-in-one default.
2. Start standalone workers with embedded equivalents disabled one at a time.
3. Verify heartbeats, claims, quota settlement, and cancellation.
4. Release B makes the production web role worker-free.

Never briefly run both old and new TTS recovery paths without the singleton lock from
phase 1.

### 8.5 Tests and acceptance

- Every role starts with only its documented lifecycle hooks.
- Web readiness does not depend on an optional worker being healthy.
- Workers stop before their pool closes.
- Generic/import N-worker claim tests still pass across processes.
- A web restart does not requeue or interrupt TTS work.
- A worker restart does not make HTTP unavailable.
- Deployment and rollback scripts restore the prior topology on failure.

## 9. Phase 3 — versioned, checksummed migrations

### 9.1 Why

`CREATE ... IF NOT EXISTS` at every startup is convenient, but it cannot express or
audit every schema evolution safely. It also couples HTTP availability to DDL and makes
partial rollout reasoning harder. A central database deserves an explicit ordered
history.

### 9.2 Recommended approach

Because the project uses raw asyncpg rather than an ORM, a small SQL migration runner is
reasonable and educational. A mature external runner is also acceptable if it preserves
the requirements below. Do not adopt an ORM solely to obtain migrations.

Suggested layout:

```text
migrations/
├── V0001__baseline.sql
├── V0002__tts_worker_controls.sql
├── V0003__outbox_and_deliveries.sql
└── ...
```

Suggested metadata table:

```sql
CREATE TABLE schema_migrations (
    version       BIGINT PRIMARY KEY,
    name          TEXT NOT NULL,
    checksum      TEXT NOT NULL,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    execution_ms  BIGINT NOT NULL,
    transactional BOOLEAN NOT NULL
);
```

Keep `app_migrations` for guarded data/business migrations unless an intentional later
change unifies the two concepts. `schema_migrations` answers “which DDL versions were
applied?”; `app_migrations` currently answers “was this one-time interpretation of legacy
data completed?” They are not automatically equivalent.

### 9.3 Runner requirements

- Acquire a stable PostgreSQL advisory migration lock before reading or applying state.
- Refuse a checksum mismatch for an already-applied migration.
- Apply pending transactional migrations one migration per transaction.
- Support explicitly declared non-transactional migrations for operations such as
  concurrent index creation. Never silently drop transaction protection.
- Stop on the first failure and return a non-zero exit.
- Log version, name, duration, and outcome without printing secrets.
- Provide `status`, `apply`, and explicit `baseline-existing` operations.
- The application should refuse to run against a schema older/newer than its supported
  range, or at minimum expose the mismatch as failed readiness.
- Production deployment should apply migrations explicitly before starting new writers.
- Local development may offer opt-in automatic application, but production should not
  hide DDL inside ordinary web startup.

### 9.4 Safe adoption of the current database

The first baseline is the risky part. Treat it as its own rollout:

1. Freeze and review the normalized schema contract.
2. Create `V0001__baseline.sql` from the current DDL, including extensions, tables,
   constraints, and indexes.
3. Prove a fresh database created by V0001 matches the schema snapshot.
4. Implement `baseline-existing` so it:
   - requires an explicit operator flag;
   - verifies the existing schema matches the expected normalized contract;
   - records V0001 without re-executing destructive DDL;
   - refuses any mismatch and prints a diagnostic diff.
5. Back up production and rehearse restore before baselining it.
6. Deploy a compatibility release that understands both the old startup path and the
   new metadata table.
7. Baseline production explicitly.
8. Only then remove ordinary startup DDL application.

### 9.5 Migration policy

- Prefer forward-fix migrations over hand-maintained down migrations.
- Before destructive or data-rewriting changes, create/rehearse a backup and use an
  expand/migrate/contract sequence.
- A migration file is immutable after application anywhere shared.
- Avoid long table rewrites in the web deployment window.
- Add columns/constraints in compatible stages when old and new application versions
  may overlap.
- Update `novelwiki/db/schema.py` compatibility entrypoints deliberately. Decide whether
  they become migration-runner aliases or remain fresh-schema helpers; do not leave two
  competing schema authorities.

### 9.6 Verification

- Fresh database → all migrations → contract snapshot match.
- Current baseline database → pending migrations → same result.
- Two concurrent migrators → one applies; the other waits/exits cleanly.
- Failure halfway through a transactional migration → no partial schema.
- Checksum alteration → hard failure.
- Old application against expanded schema and new application against pre-contract
  schema are tested where rolling overlap is possible.

## 10. Phase 4 — filesystem inventory and reconciliation

### 10.1 Why

PostgreSQL cannot transact atomically with ordinary filesystem writes. The database can
commit while a file write fails, or a file can be published while its manifest insert
fails. Deletion can remove rows while post-commit cleanup crashes. Backups can restore
the database and volume to different moments.

The solution is not necessarily storing blobs in PostgreSQL. It is deterministic file
identity, careful publication, durable cleanup, and reconciliation.

### 10.2 Artifact inventory

| Artifact | Authoritative metadata | Bytes | Derivable? |
|---|---|---|---|
| Extracted images/assets | `assets` | `ASSET_DIR` | some are not |
| User avatars | `users.avatar_path` | `ASSET_DIR/_users` | no |
| Narration audio | `chapter_audio` | `AUDIO_DIR` | regenerable but costly |
| Import originals | `import_jobs.original_path` and storage conventions | `IMPORT_DIR` | no |
| Import scratch | job/storage conventions | `IMPORT_DIR` | yes |
| BM25 indexes | chunks + on-disk metadata | `BM25_INDEX_PATH` | yes |
| AGY workspaces | `ai_execution_runs.workspace_relpath` | `AGY_WORK_DIR` | retained temporarily |

### 10.3 Report-only reconciler first

Add an operator command/service with scopes such as:

```text
reconcile-storage --scope all --mode report --json
reconcile-storage --scope audio --novel-id 42 --mode report
reconcile-storage --scope imports --verify-hashes --mode report
```

It should classify, not immediately delete:

- manifest row points to a missing file;
- manifest path escapes its configured root;
- file size differs from metadata;
- hash differs where a hash is available;
- file has no manifest/reference;
- temporary file is older than its allowed session/operation;
- audio/BM25 directory belongs to a deleted novel;
- old audio content versions are no longer reachable;
- AGY workspace is beyond retention;
- import job is terminal but scratch remains.

Hashing large files must be optional or rate-limited. A cheap existence/size pass should
be the default.

### 10.4 Repair modes

Add narrow, explicit repairs only after report mode has production history:

- `delete-orphan-derivatives`: safe for rebuildable BM25 and approved scratch;
- `delete-superseded-audio`: only when current manifests make it unreachable;
- `mark-missing`: update/report a broken cache manifest so the product regenerates;
- `rebuild-bm25`: schedule/rebuild, not hand-edit files;
- `quarantine-orphans`: move uncertain files rather than deleting them.

Never make `--repair` the default. Require confirmation unless a narrowly scoped,
reviewed maintenance worker owns the action.

### 10.5 Safer file publication

For newly generated artifacts:

1. Write to a job/run-scoped temporary path under the same filesystem.
2. Close and optionally `fsync` the file.
3. Validate size/format and compute a content hash where useful.
4. Atomically rename into its deterministic final path.
5. Upsert the database manifest idempotently.
6. If the manifest write fails, leave a recognizable orphan for the reconciler rather
   than publishing an ambiguous path.

No ordering removes every crash window; deterministic paths and reconciliation make
each window recoverable.

Consider adding `sha256` to `chapter_audio`, because current audio manifests record path,
duration, and byte count but not content integrity.

### 10.6 Acceptance

- Report mode never mutates data.
- Path traversal/symlink defenses are tested.
- A missing, corrupt, orphaned, superseded, and temporary artifact fixture is classified
  correctly for every root.
- Repair actions are idempotent.
- A full report can run without starving web requests or workers.
- Output contains identifiers and paths needed by an operator but not story text or
  secrets.

## 11. Phase 5 — transactional event bus with `LISTEN/NOTIFY`

### 11.1 What to build

Build a small PostgreSQL event bus, not a clone of a general-purpose broker. Work should
own the persistence mechanics unless phase 0 deliberately chooses a new Eventing module.
Bootstrap should own the consumer registry and hand handlers to the event worker, like
the existing generic job registry.

Recommended tables:

```sql
CREATE TABLE outbox_events (
    id                  BIGSERIAL PRIMARY KEY,
    event_type          TEXT NOT NULL,
    schema_version      SMALLINT NOT NULL DEFAULT 1,
    producer_module     TEXT NOT NULL,
    aggregate_type      TEXT NOT NULL,
    aggregate_id        TEXT NOT NULL,
    payload             JSONB NOT NULL DEFAULT '{}',
    request_id          TEXT,
    correlation_id      UUID,
    causation_event_id  BIGINT REFERENCES outbox_events(id) ON DELETE SET NULL,
    available_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    fanout_completed_at TIMESTAMPTZ,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX outbox_pending_fanout_idx
    ON outbox_events (available_at, id)
    WHERE fanout_completed_at IS NULL;

CREATE TABLE event_deliveries (
    event_id       BIGINT NOT NULL REFERENCES outbox_events(id) ON DELETE CASCADE,
    consumer       TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','running','retry','done','dead')),
    attempts       INT NOT NULL DEFAULT 0,
    max_attempts   INT NOT NULL DEFAULT 5,
    available_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    claim_token    UUID,
    claimed_at     TIMESTAMPTZ,
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at   TIMESTAMPTZ,
    PRIMARY KEY (event_id, consumer)
);

CREATE INDEX event_delivery_claim_idx
    ON event_deliveries (status, available_at, event_id);

CREATE INDEX event_delivery_dead_idx
    ON event_deliveries (consumer, updated_at)
    WHERE status = 'dead';
```

The exact DDL must be refined for ownership, retention queries, and actual access
patterns. If event processing can run longer than the standard lease, add heartbeat
renewal. Keep payloads small and versioned; prefer identifiers over copying entire
chapters or sensitive content.

### 11.2 Atomic emission

Expose a Work public transaction capability, for example:

```python
class EventOutboxTransactionApi(Protocol):
    async def append(self, event: ProposedEvent) -> int: ...
```

An operation that changes owner A's state and emits an event binds owner A plus Work in
one named workflow. Inserting the event after commit is not acceptable: a process crash
could commit the fact without the event.

The append SQL also calls `pg_notify` in the transaction:

```sql
SELECT pg_notify('novelwiki_events', event_id::text);
```

PostgreSQL delivers the notification only after commit. The event row remains the truth
if no listener is connected.

### 11.3 Listener design

- Use a dedicated asyncpg connection for `LISTEN novelwiki_events`.
- A notification sets an in-process wake event; it does not directly execute the
  payload.
- On wake, drain eligible database rows until none remain.
- Retain a timeout-based polling fallback, likely slower than the current two seconds
  (for example 5–30 seconds, chosen from measured latency needs).
- Reconnect with bounded exponential backoff after connection loss.
- After reconnect, immediately drain rows before waiting for another notification.
- Coalescing or losing notifications is harmless because the drain query is
  authoritative.

The same wake-up pattern may later accelerate `jobs`, `import_jobs`, and `tts_jobs`, but
use separate stable channels or a well-defined shared payload. Do not make queue
correctness depend on it.

### 11.4 Fan-out dispatcher

Bootstrap maintains a static, version-controlled registry:

```text
event type          consumer name              handler
novel.deleted.v1 -> acquisition.file-cleanup -> Acquisition public capability
                  -> narration.audio-cleanup -> Narration public capability
                  -> codex.bm25-cleanup       -> Codex public capability
```

Static registration is preferable to a mutable subscription table initially: code and
consumer deployment remain reviewable together.

Fan-out algorithm:

1. Claim eligible events whose `fanout_completed_at IS NULL` using
   `FOR UPDATE SKIP LOCKED`.
2. Resolve registered consumers for `(event_type, schema_version)`.
3. Insert one `event_deliveries` row per consumer with `ON CONFLICT DO NOTHING`.
4. Set `fanout_completed_at` in the same transaction.
5. If there are no consumers, deliberately mark fan-out complete and record a metric;
   do not leave the event spinning forever.
6. An unknown event version should be visible as an error, not silently sent to a
   handler expecting another schema.

Newly introduced consumers do not automatically receive old events. A separate replay
operation can create missing delivery rows over an explicit event range.

### 11.5 Delivery processing

1. Atomically claim one eligible delivery using `FOR UPDATE SKIP LOCKED`.
2. Move it to `running`, increment `attempts`, stamp `claim_token` and `claimed_at`.
3. Load the immutable event envelope.
4. Invoke the registered consumer handler.
5. On success, mark `done` and `processed_at`.
6. On retryable failure, clear the lease, set `retry`, record a bounded error summary,
   and calculate exponential backoff with jitter.
7. At `max_attempts`, mark `dead`.
8. Reclaim only expired `running` leases; never requeue every running delivery at boot.

### 11.6 Delivery semantics and idempotency

The system provides **at-least-once delivery**, not exactly once.

Every handler must document its idempotency strategy:

- Deleting an already-absent directory succeeds.
- Scheduling a follow-up job uses `event:<event_id>:<consumer>` as an idempotency key.
- A database projection uses `(event_id, consumer)` or a natural unique constraint.
- Sending an external notification stores a provider/idempotency marker when the
  provider supports it.
- A handler must not rely on mutable “current state” when the event needs historical
  facts that deletion removed; include the minimum required facts in the payload.

For a database-only consumer, it may be possible to commit the consumer effect and
delivery completion in one UoW transaction. That is stronger but must still obey table
ownership. Do not expose raw connections to handlers to obtain this shortcut.

### 11.7 First vertical slice: `novel.deleted.v1`

This is a useful first event because deletion currently has post-commit filesystem work
and known audio/BM25 cleanup debt.

Emission:

- Extend the named `delete_novel` workflow to bind Work's event-outbox transaction
  capability.
- Before deleting/cascading rows, collect the minimal deterministic cleanup identity:
  `novel_id`, relevant import job IDs, and any non-derivable path identities that cannot
  be reconstructed afterward.
- Delete the Catalog root and append `novel.deleted.v1` in the same transaction.
- Authorization, row cascades, and database cache invalidation remain synchronous.

Initial consumers:

- `acquisition.file-cleanup.v1`: remove import job artifacts and extracted assets under
  the allowed novel/job roots;
- `narration.audio-cleanup.v1`: remove the novel's audio directory/artifacts;
- `codex.bm25-cleanup.v1`: remove the rebuildable BM25 directory and in-process manager
  reference if applicable.

During rollout, existing synchronous post-commit cleanup may run alongside the new
consumer if both paths are idempotent. Remove the old path only after event delivery and
dead-letter visibility have been proven.

### 11.8 Events to consider later

- `import.committed.v1`: analytics/projection updates or optional follow-up scheduling;
- `translation.completed.v1`: derivative work that is safe after the content commit;
- `codex.build.completed.v1`: health/projection/notification reactions;
- `job.failed.v1`: operator notifications;
- `user.deleted.v1`: external artifact cleanup;
- `chapter.content_changed.v1`: derivative cleanup or rebuild scheduling.

Do **not** use asynchronous events for anything that could temporarily violate spoiler
safety, charge quota incorrectly, expose unauthorized content, or publish inconsistent
base text. For example, cache invalidation that prevents stale spoiler-bearing answers
may need to remain in the content transaction or use generation keys that make stale
rows unreachable immediately.

### 11.9 Dead letters, replay, and retention

Operator operations:

```text
event-status --event-id <id>
event-dead --consumer <name>
event-redrive --event-id <id> --consumer <name>
event-replay --type <type> --from-id <n> --to-id <n> --consumer <name> --dry-run
```

Redrive should create/reset only the selected delivery after validating that the
consumer still supports the event schema. Preserve attempt history through audit events
or a later `event_delivery_attempts` table.

Retention policy:

- Keep events while any delivery is non-terminal.
- Keep dead deliveries until explicitly resolved or archived.
- Retain completed events long enough for debugging/replay (for example 30–90 days,
  chosen explicitly).
- Delete in bounded batches to avoid large transactions and vacuum spikes.
- Metrics must distinguish completed retention from unprocessed backlog.

### 11.10 Event-bus acceptance tests

- State change and event commit together; either both exist or neither does.
- Transaction rollback produces no visible notification/event.
- Listener disconnected during emission: polling later processes the event.
- Duplicate notifications produce one set of deliveries.
- Two dispatchers create one delivery per consumer.
- Two consumers claim different delivery rows safely.
- Consumer crash after external effect but before `done`: retry is harmless.
- Stale lease is recovered; live heartbeating lease is not stolen.
- Retry backoff and `max_attempts → dead` work.
- Redrive processes only the requested delivery.
- Replay is idempotent because of the delivery primary key.
- Unknown event versions are visible and safe.
- Event payloads never exceed configured size or contain prohibited secrets/story text.

## 12. Phase 6 — cache identity, retention, and stampede control

### 12.1 Problem

Current cache keys primarily identify novel, question/entity, and spoiler ceiling. Cache
rows may survive a prompt change, model change, retrieval configuration change, or other
code change unless a separate invalidation path deletes them. TTL alone is not a
complete correctness strategy.

### 12.2 Recommended identity model

Introduce two independent identities:

1. **Knowledge generation:** a monotonically increasing Codex-owned generation for a
   novel. Any committed change that makes prior synthesized output unsafe or stale bumps
   the generation in the same transaction or makes the old generation unreachable.
2. **Synthesis fingerprint:** a stable hash of code/config inputs that affect the answer,
   such as prompt version, model label, retrieval algorithm version, embedding/rerank
   model family, and relevant tool policy.

A possible Codex-owned table:

```sql
CREATE TABLE codex_novel_state (
    novel_id             BIGINT PRIMARY KEY REFERENCES novels(id) ON DELETE CASCADE,
    knowledge_generation BIGINT NOT NULL DEFAULT 1,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Cache uniqueness then includes generation and fingerprint:

```text
query_cache:
  (novel_id, query_hash, chapter_ceiling, knowledge_generation, synthesis_fingerprint)

wiki_cache:
  (novel_id, entity_id, chapter_ceiling, knowledge_generation, synthesis_fingerprint)
```

Old rows can remain temporarily but are unreachable. A maintenance pass deletes them in
batches. This is safer than relying only on delete-based invalidation.

The exact generation bump workflow must be designed with Reading/Codex ownership. A
content commit that must atomically invalidate Codex output may need a named workflow
binding both modules. Do not let an asynchronous event create a stale-answer window.

### 12.3 TTL and retention

Add `expires_at` only as a cost/storage/freshness policy, not the primary correctness
key. Suggested behavior:

- lookup requires `expires_at IS NULL OR expires_at > now()`;
- cleanup deletes expired and obsolete-generation rows in bounded batches;
- per-novel or global maximum age/row count is configurable;
- model/prompt upgrades can invalidate immediately through fingerprint changes;
- no cleanup transaction deletes an unbounded number of rows.

Avoid updating `last_accessed_at` on every hit unless measurements justify the write
amplification. Options include sampled access updates, approximate counters, or simple
age/generation retention instead of true LRU.

### 12.4 Stampede control

Two identical cache misses can trigger duplicate expensive AI work. Do not hold a pooled
PostgreSQL connection and session advisory lock for a long model call. Prefer a short
lease row keyed by the complete cache identity:

- acquire with an atomic insert/lease takeover;
- owner periodically renews if the call can exceed the lease;
- non-owners wait briefly, poll for the completed cache row, or return a retry response;
- crashed fills expire;
- successful owner stores the cache row and removes/releases the fill lease.

This can be a dedicated `cache_fill_locks` table or a carefully generalized existing AI
lock mechanism. Keep per-user denial-of-wallet concurrency separate from per-key
stampede prevention; they answer different questions.

### 12.5 Metrics and tests

Track by cache kind:

- hit, miss, expired, obsolete-generation, and fill-wait counts;
- rows/bytes and oldest entry;
- provider work avoided;
- invalidation/generation bumps;
- cleanup duration and rows deleted.

Tests must cover content changes, ceiling changes, prompt/model fingerprint changes,
expiry, concurrent identical misses, failed fill-owner recovery, and batch cleanup.

## 13. Phase 7 — queue operations and controlled enhancements

### 13.1 Build operator recovery before broker features

The existing queues already have durable rows, attempts, errors, and terminal `failed`
states. Treat `failed` as the current dead-letter bucket and add safe tooling around it.

Recommended features:

- inspect a job including lease, attempts, quota state, current/previous execution runs,
  and bounded error summaries;
- list oldest queued/running/waiting jobs by kind/backend;
- redrive a failed/canceled job intentionally;
- pause claiming by queue, kind, or backend without changing already-running jobs;
- report/recover stale leases;
- show whether a job is blocked by provider wait, quota, policy, sidecar, or worker health;
- preserve a per-attempt history for non-AGY jobs, either in a new owned table or in
  structured audit events.

### 13.2 Redrive semantics

Prefer creating a new job linked by `retry_of_job_id` over mutating a terminal historical
row. Benefits:

- original failure remains auditable;
- attempts and quota semantics restart explicitly;
- current idempotency/dedupe rules can be applied deliberately;
- an operator can compare the failed and replacement execution.

Redrive must re-run authorization/policy and decide quota semantics explicitly. Never
silently charge or reuse a finalized reservation.

### 13.3 Optional priority

Only add priority after identifying product classes that require it, for example one
interactive chapter ahead of a 100-chapter batch. A minimal design adds bounded
`priority SMALLINT` and claims by:

```sql
ORDER BY priority DESC, available_at ASC, created_at ASC
```

Add the matching partial queue index. Protect against starvation through a small bounded
range, aging, or separate concurrency reservations. Do not allow arbitrary user-provided
priority.

### 13.4 Routing and fan-out boundaries

- Existing `kind` and `execution_backend` already provide useful routing.
- Keep job routing static in Bootstrap registries.
- Use the event bus for one-to-many reactions.
- Do not add topic wildcards, exchanges, consumer groups, or dynamic routing unless an
  actual product requirement appears.

## 14. Phase 8 — observability and fault injection

### 14.1 Three different records

Do not conflate:

- **Logs:** detailed chronological diagnostics for one process;
- **Audit events:** durable business/operator actions and lifecycle facts;
- **Metrics:** aggregate health and performance over time.

Propagate identifiers across all three:

- request ID;
- job/import/TTS job ID;
- AI execution run ID;
- event ID and causation/correlation IDs;
- worker ID and claim token where operationally useful.

### 14.2 Minimum metrics

Database:

- pool in-use/waiting counts and acquisition latency;
- query/transaction latency by operation, not raw user text;
- deadlocks, lock waits, connection failures;
- relation/index sizes, dead tuples, vacuum/analyze age where available.

Jobs/events:

- queued/running/retry/waiting/dead counts;
- oldest eligible row age;
- claim-to-start and total duration;
- attempts, failures, cancellations, stale-lease recoveries;
- notification wakeups versus polling wakeups;
- event fan-out lag and delivery lag per consumer;
- TTS singleton leader/standby state.

Caches/retrieval/providers:

- cache hit/miss/fill-wait ratios;
- vector, BM25, fusion, and rerank latency;
- provider calls, failures, wait states, and cost/quota settlement;
- TTS generation duration, real-time factor if measurable, and cache reuse.

Storage:

- bytes/files by root and artifact class;
- reconciliation anomaly counts;
- cleanup successes/failures;
- backup age and last successful restore rehearsal.

### 14.3 Health/readiness

- Liveness: process event loop is responsive.
- Readiness: required database connection/schema version is healthy.
- Worker health: last successful claim/poll/heartbeat and current role state.
- Optional sidecars/providers should degrade their feature, not necessarily web
  readiness.
- Queue backlog should be visible but should not automatically make the web server
  unready unless the product deliberately chooses that policy.

### 14.4 Fault-injection scenarios

Automate or document tests that:

- kill a worker after claim but before work;
- kill it after external file effect but before marking success;
- lose the TTS leader-lock connection;
- disconnect the event listener during commits;
- run two dispatchers and two consumers;
- hold a lease heartbeat while another recovery sweep runs;
- make PostgreSQL temporarily unavailable;
- fill or make the artifact volume read-only;
- delete/corrupt a cached audio or BM25 artifact;
- deploy/restart while every job kind is running;
- duplicate event delivery;
- fail quota finalization and retry it;
- interrupt a migration;
- restore database and filesystem from mismatched points and run reconciliation.

The goal is not chaos for its own sake. Each test should prove a documented recovery
property.

## 15. Phase 9 — coordinated backup, restore, and repair

### 15.1 Recovery unit

`pg_dump` protects database state but not all valuable bytes. A recoverable Tideglass
instance consists of:

- PostgreSQL database;
- non-derivable assets, avatars, audio if preserving generation cost matters, and import
  originals;
- deployment configuration/secrets stored through the operator's secure mechanism;
- application image/source revision;
- optional derivative indexes and scratch, which can be rebuilt or discarded.

### 15.2 Backup modes

For the current single-host scale, a clear stop-the-writers backup is acceptable and
easiest to reason about:

1. enter maintenance mode or stop web/worker writers;
2. create a custom-format PostgreSQL dump and checksum it;
3. snapshot/archive the persistent artifact roots and checksum the archive/manifest;
4. record database name/version, schema migration version, application image revision,
   filesystem snapshot identity, timestamps, and exclusions in one backup manifest;
5. restart writers;
6. verify `pg_restore --list` and archive readability.

For lower downtime later, use immutable/content-addressed artifact publication plus
filesystem snapshots/object versioning and PostgreSQL WAL/PITR. Define the acceptable
consistency window explicitly; do not assume two independent timestamps form one atomic
backup.

### 15.3 Restore rehearsal

Restore into a disposable environment:

1. restore PostgreSQL into a new database;
2. restore artifact roots into new directories/volume;
3. verify migration version and extensions;
4. run the storage reconciler in report mode;
5. rebuild derivative BM25 indexes if excluded;
6. run contract-aware backend smoke tests and a real browser smoke;
7. verify one cached read, one vector retrieval, one worker claim/recovery, and one audio
   range request;
8. record duration, anomalies, and the tested application/database versions.

Define recovery objectives only after measuring this rehearsal:

- **RPO:** maximum acceptable data loss;
- **RTO:** maximum acceptable time to restore service.

## 16. Optional learning experiments after the core roadmap

### 16.1 PostgreSQL full-text search comparison

Prototype `tsvector` + GIN lexical search over chunks and compare it with persisted
`bm25s` on:

- retrieval quality over a fixed question set;
- spoiler-ceiling correctness;
- build/update time;
- disk/database size;
- cold and warm latency;
- concurrent request impact;
- operational simplicity.

Do not replace BM25 because “everything should be in PostgreSQL.” Replace it only if the
measured product/operational tradeoff is better.

### 16.2 PostgreSQL row-level security

RLS could provide defense in depth for user-owned rows, but it interacts with connection
pooling, admin/system operations, shared/global novels, background workers, and per-
transaction user context. Prototype it on a disposable branch/database first. Application
authorization remains required even if RLS is added.

### 16.3 Replayable projections

Use retained events to build one disposable read model from scratch. This teaches schema
versioning, replay, idempotency, ordering, and projection cutover without making the
entire application event-sourced.

### 16.4 Controlled concurrency

After separate workers and metrics exist, add bounded per-kind concurrency where it
improves throughput. Respect database pool capacity, provider limits, GPU limits, and
per-user fairness. Do not simply spawn one task per queued row.

## 17. Cross-cutting test matrix

Every phase selects the applicable rows from this matrix:

| Layer | Required evidence |
|---|---|
| Unit | state transitions, backoff, fingerprints, path classification, registry validation |
| Repository | SQL constraints, claims, leases, indexes, transaction rollback |
| Workflow | multi-owner atomicity and compensation boundaries |
| Concurrency | two claimers, duplicate delivery, leader election, stale/live leases |
| Crash recovery | process death before/after each durable boundary |
| Contract | schema, CLI, route, response, and job/event state snapshots where exposed |
| Architecture | table ownership, inbound SQL ban, dependency graph, public surfaces |
| Security | ownership, admin gates, path traversal, payload redaction, CSRF for new routes |
| Performance | queue/event claim query plans, cleanup batching, cache/read latency |
| Deployment | old/new overlap, role cutover, migration locking, rollback image |
| Recovery | database + filesystem restore and reconciliation |

Useful existing commands include:

```bash
uv run pytest
uv run python tools/check_architecture.py
uv run python tools/benchmark_queries.py
uv run python scripts/contracts.py --update   # only for intentional contract changes
git diff --check
```

Database-backed suites must use a disposable test database. Never point destructive
tests or migration-baseline experiments at production.

## 18. Rollout and rollback rules

### 18.1 Expand/migrate/contract

For schema and topology changes:

1. **Expand:** add compatible columns/tables/entrypoints; old code continues to work.
2. **Migrate/cut over:** populate state, enable new roles/consumers, observe both paths.
3. **Contract:** remove old startup DDL, embedded workers, old columns, or synchronous
   cleanup only after the new path is proven.

### 18.2 Feature switches

Use explicit, temporary switches for dangerous cutovers:

- embedded generic/import/TTS workers enabled;
- standalone role enabled;
- event emission enabled;
- individual event consumer enabled;
- synchronous legacy cleanup enabled;
- cache-generation lookup enabled;
- automatic repair disabled by default.

Document removal criteria. Permanent layers of dead switches are not a rollback strategy.

### 18.3 Rollback compatibility

- The previous application image must tolerate the expanded schema.
- Do not deploy a destructive contract migration in the same release that first uses the
  replacement.
- New event types should be harmless if an older consumer is absent; rows wait durably.
- A rollback must not start embedded TTS recovery beside a standalone leader without the
  singleton lock.
- When schema/data rollback is required, stop writers and restore into a new database as
  documented by the release runbook.

## 19. Documentation and contract impact checklist

For each implemented phase, assess and update the applicable living pages:

| Change | Living documentation likely affected |
|---|---|
| TTS leadership/topology | `docs/pipelines/narration.md`, background jobs, deployment, configuration |
| Separate worker roles | composition root, deployment, configuration, CLI if applicable |
| Migrations | database schema, deployment, release runbook, testing |
| Storage reconciler | filesystem layout, CLI/API, operations/security |
| Event bus | architecture overview/workflows/module ownership, background jobs, schema, glossary |
| Cache generation/TTL | Codex module/pipeline, schema, configuration |
| Queue operator tools | Work/Experience modules, API/CLI, background jobs, release runbook |
| Metrics/health | platform, deployment, configuration, operations |
| Backup changes | filesystem layout, deployment, release runbook |

Also:

- add/update ADRs for durable architectural decisions;
- update `TABLE_OWNERS` for new tables;
- update workflow participant maps for event-emitting workflows;
- regenerate schema/CLI/routes/job-state snapshots for intentional external changes;
- update root and `docs/README.md` maps when adding or moving pages;
- never edit historical migration/equivalence reports to pretend future work already
  existed.

## 20. Things deliberately deferred

Reconsider these only after metrics show a limitation:

- Redis for hot ephemeral caching or extremely high counter traffic;
- RabbitMQ/NATS/Kafka for cross-service routing, high throughput, or independent service
  ownership;
- a dedicated vector database for distributed scale or specialized filtered ANN needs;
- MongoDB for a genuinely document-first bounded context;
- TTS multi-worker leasing before multiple sidecars/GPUs;
- table partitioning, PgBouncer, read replicas, or sharding;
- Kubernetes.

Adding a service should follow a written problem statement, measured evidence, failure
model, operator ownership, backup story, and exit plan.

## 21. “I forgot the conversation” restart checklist

If returning to this plan months later:

1. Read the living docs linked in section 2; assume this plan is stale wherever code and
   living docs disagree.
2. Inspect `git log`, current schema snapshots, Compose topology, and worker lifecycle.
3. Measure current database/queue/storage scale again; do not rely on the dated baseline.
4. Run the full existing test and architecture gates before changing behavior.
5. Start with phase 1 unless it has already landed: enforce one TTS leader before adding
   web replicas or standalone TTS processes.
6. Do not build fan-out from raw `LISTEN/NOTIFY`. Build durable outbox and delivery rows;
   use notifications only to wake a database-draining worker.
7. Keep jobs and events distinct.
8. Preserve synchronous permission, quota, spoiler, and content invariants.
9. Make every external event consumer idempotent and prove duplicate delivery.
10. Roll out one vertical slice—preferably `novel.deleted.v1` cleanup—before adding more
    event types.
11. Update living documentation only for behavior actually implemented.
12. Rehearse rollback and restore before declaring a phase complete.

The desired outcome is not “Tideglass has its own RabbitMQ.” It is a small system whose
durable state, work, events, caches, files, and recovery procedures are understandable
and testable end to end, while PostgreSQL remains the center of gravity.
