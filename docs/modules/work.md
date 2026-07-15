# Work module (`novelwiki/modules/work/`)

**Responsibility:** the **generic durable-job system** — the one queue behind scrapes,
codex builds, translation batches, and the admin AGY smoke test. Work owns scheduling
with idempotent dedupe, atomic leased claiming, heartbeats and crash recovery, retries,
cooperative cancellation, provider-wait parking, and exactly-once quota settlement.
The operational walkthrough is
[../pipelines/background-jobs-and-quota.md](../pipelines/background-jobs-and-quota.md).

**Owned table:** `jobs`.

Work is deliberately **domain-ignorant**: it knows *kinds* and *state transitions*, never
what a scrape is. Handlers are registered by Bootstrap
([composition-root.md §4](../architecture/composition-root.md)).

---

## Public contract (`public.py` → `application/contracts.py`)

- **`ScheduledJob`** — what `schedule()` returns (id + created/deduped flag).
- **`WorkApi`** — `schedule(kind, **options)`, `cancel(job_id, user_id)` — the capability
  feature modules receive (behind their own ports, e.g. `CodexWorkPort`,
  `TranslationWorkPort`).
- **`WorkTransactionApi`** — `increment_quota_consumed(job_id, units)` — bound inside the
  `commit_translation` workflow so metering lands with the domain write.
- **`WorkQuotaFinalizationTransactionApi` + `JobQuotaSettlement`** — the finalization
  half of the `finalize_job_quota` workflow (Work computes the refundable remainder and
  flips `quota_finalized`; Identity refunds — one transaction).

## The job row (see [database-schema.md](../data/database-schema.md) for every column)

Key fields: `kind` (`scrape` | `codex_build` | `translate` | `agy_smoke`), `status`
(`queued` | `running` | `waiting_provider` | `done` | `failed` | `canceled`), `stage` +
`progress` (live UI), `options` (kind-specific args), `idempotency_key` (partial-unique
over **active** statuses — a repeated click dedupes onto the running job instead of
double-charging), the quota triple `quota_kind`/`quota_reserved`/`quota_consumed` +
`quota_finalized` (double-refund guard), `attempts`/`max_attempts`
(`JOB_MAX_ATTEMPTS`=3), the lease pair `claim_token`/`claimed_at`, and the AI-backend
block (`backend_requested` auto|api|agy, `execution_backend` api|agy,
`backend_policy_version`, `backend_fallback_allowed`/`_from`, `backend_model`,
`not_before`, `cancel_requested_at`).

## The worker (`adapters/inbound/worker.py` + `application/worker*.py`)

A DB-polled loop (started by the lifecycle; also safe as extra processes) whose every
decision lives in application services:

- **Claim** (`adapters/outbound/claims.py::claim_next` — shared with the AGY worker):
  one `UPDATE … FOR UPDATE SKIP LOCKED` moves the oldest eligible `queued` job (of this
  worker's `execution_backend` + registered kinds, respecting `not_before`) to
  `running`, bumps `attempts`, stamps this process's opaque `claim_token` +
  `claimed_at`. Two workers can never hold the same job.
- **Heartbeat** — renews `claimed_at` every `JOB_WORKER_HEARTBEAT_SECONDS` (30) while the
  handler runs.
- **Recovery** (`WorkerStateService.recover_stale_leases`) — a `running` job whose lease
  is older than `JOB_LEASE_TIMEOUT_SECONDS` (180) is provably orphaned: requeue (attempts
  remaining) / fail / cancel per its cancel flag. **No requeue-everything-on-boot** — that
  would steal a sibling worker's live job.
- **Execution** — resolve the handler from the injected registry; hand it the job + an
  execution context (`bail_if_canceled`, `set_progress`, `update_job`, `load_user`,
  `pending_translations`). Handlers raise the internal canceled signal to unwind cleanly.
- **Cancellation** — `cancel_job` marks intent; a queued job is never claimed
  (`mark_canceled_if_running` / status guards); a running one stops at its next
  `bail_if_canceled()` — i.e. before the next expensive stage, keeping finished work.
- **Retry** — `fail_or_retry`: crashed attempt → back to `queued` while
  `attempts < max_attempts`, else `failed` (with `error`).
- **Provider wait** — `wait_for_provider(job_id, failure_code, error, minutes)`: parks an
  AGY job as `waiting_provider` with `not_before = now + minutes` (no lease held, no
  tight retry loop when the subscription/quota is exhausted);
  `release_due_provider_waits` makes due rows claimable; admins can force it via
  `retry_waiting` (`POST /api/admin/ai/agy/retry-waiting`).
- **Finalization** — on any terminal state, exactly once (guarded by
  `quota_finalized`), through the `finalize_job_quota` workflow: success keeps the full
  reservation; failure/cancel refunds `reserved − consumed` (clamped ≥ 0). Translation
  additionally has `release_translation_reservation_for_fallback` (refund AGY's unused
  reservation before the API backend re-meters remaining chapters).
- **Audit** — every transition logs an `audit_events` row (`job.created`, `job.done`,
  `job.failed`, `quota.refund`, …) tagged with the request id that scheduled it.

## Scheduling & dedupe (`adapters/outbound/postgres.py`)

`create_job(...)` inserts or returns the existing **active** job with the same
`idempotency_key` (the partial unique index includes `waiting_provider`, so
capacity-parked AGY work still dedupes). `ActiveJobLimitError` and
`BackendPolicyChangedError` surface the per-user AGY concurrency cap and
policy-version drift as typed errors the schedulers translate.

## HTTP surface (`adapters/inbound/http.py`, auth required)

- `GET /api/jobs` — filtered listing (`kind`, `status`, `novel_id`, `active`, `limit`);
  **non-admins are hard-scoped to their own jobs**, admins may pass `user_id`.
  Rows are enriched with current AI-run metadata via injected ports
  (`JobMetadataPort`) — Work never queries AI Execution storage itself. In the web
  composition, an injected observation port emits a detailed `job.snapshot_changed`
  structured log after enrichment and suppresses identical snapshots across subsequent
  UI polls. The generic successful HTTP access record for this list route is omitted;
  route failures retain `http.request.completed`/`failed` logging.
- `GET /api/jobs/{id}` — same ownership rule.
- `POST /api/jobs/{id}/cancel`.

(The cross-system feed `GET /api/activity` — generic + import + TTS in one list — is an
Experience projection, not Work.)

## Collaboration notes

- Feature modules never insert into `jobs` directly — they schedule through injected
  Work bridges, inside the `schedule_ai_job` compensation shape (reserve → schedule →
  refund on failure/dedupe; ADR 003).
- The AGY host worker claims from the *same table* with
  `execution_backend='agy'` — one queue, two executors
  ([ai-execution.md](ai-execution.md)).
