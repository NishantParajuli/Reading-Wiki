# Pipeline: durable background jobs & the quota lifecycle

> Long-running, user-visible pipelines run as **durable jobs** — rows advanced by polling
> workers, not fire-and-forget framework tasks. Short read-path AI (Ask/profile/recap)
> and on-demand translation still execute inline behind their own cost/concurrency
> guards. This page explains the durable machinery and follows one job through its life.

## Why durable

A deploy here is an image rebuild: every in-process task dies. Before this design, a
restart could kill work *after* quota was reserved (silent loss + silent charge), and a
double-click could schedule the same expensive work twice. Durability, leases, dedupe,
and explicit settlement fix all three.

## The three job systems (+ one executor split)

| System | Table | Worker | Kinds / scope |
|---|---|---|---|
| Generic (Work module) | `jobs` | `modules/work/adapters/inbound/worker.py` (in-process; N instances safe) | `scrape`, `codex_build`, `translate`, `agy_smoke` |
| Import (Acquisition) | `import_jobs` | import worker (in-process; standalone via `import-worker` CLI; N safe) | EPUB/PDF pipeline stages |
| Narration | `tts_jobs` | TTS worker (in-process, single-instance design) | `chapter` / `book` narration |
| AGY executor | same `jobs` table, `execution_backend='agy'` | dedicated host worker (`python -m novelwiki.agy.worker`, systemd) | AGY-granted codex/translate (+ smoke) |

All are surfaced together in `GET /api/activity` (Experience) and individually via their
own endpoints. States are contract-frozen in
`tests/contracts/snapshots/job_states.json`.

## Claiming and recovery (two models)

The generic Work and Import workers share the concurrency-safe claim–lease core:

1. **Atomic claim** — one `UPDATE … WHERE status IN (trigger states) … FOR UPDATE SKIP
   LOCKED` moves the oldest eligible row into a **distinct in-progress status**, bumps
   `attempts`, and stamps the worker's opaque per-process `claim_token` + `claimed_at`.
   Because the in-progress status is not a trigger status, a claimed job leaves the queue
   the instant it's claimed — two workers can never process the same job.
2. **Heartbeat** — the owner renews `claimed_at` every `*_HEARTBEAT_SECONDS` (30) while
   working.
3. **Lease-expiry recovery only** — a maintenance sweep requeues an in-progress job
   *only* when its lease has gone unrenewed past `*_LEASE_TIMEOUT_SECONDS`
   (120 import / 180 generic), i.e. its owner is provably gone. There is deliberately
   **no "requeue everything on boot"** — that would steal live jobs from sibling workers.
4. **Cooperative cancel** — `cancel` marks intent; queued jobs are simply never claimed;
   running handlers call `bail_if_canceled()` between expensive stages, so completed
   units are kept.
5. **Retry** — a crashed attempt goes back to `queued` while `attempts < max_attempts`
   (3), else `failed` with the error recorded.

TTS is the explicit alternate model: it has no `claim_token`/heartbeat lease columns,
assumes one worker per database, and requeues `generating → queued` at startup. Audio
generation is cache-idempotent and protected by a PostgreSQL advisory target lock, but
operators must not start multiple TTS worker processes because one startup could requeue
another process's live job.

## Life of a codex build (worked example)

1. **Schedule** — `POST /api/novels/42/codex/build` →
   `CodexCommandService.schedule_build`: Catalog editable check → AI-backend resolution →
   **quota reserve** (1 × `codex_builds` via Identity) → `create_job(kind='codex_build',
   idempotency_key='codex:novel42:None:None:0', quota_kind='codex_builds',
   quota_reserved=1, …)`. The final key fields are `from`, `to`, and `force`, so
   different ranges are independently deduplicated.
   - If an active job with that key exists (`queued`/`running`/`waiting_provider`), the
     insert **dedupes** onto it and the reservation is refunded — a double-click costs
     nothing (the `schedule_ai_job` compensation shape; ADR 003 documents the accepted
     crash window between reserve and insert).
2. **Claim & run** — a generic worker claims it, heartbeats, and dispatches to the
   handler Bootstrap registered for `codex_build`, which runs chunk → embed → extract →
   rebuild-BM25 with `set_progress`/`stage` updates (live in the UI) and cancel checks
   between stages.
3. **Terminal + settle** — on `done`/`failed`/`canceled`, the worker finalizes **exactly
   once** through the `finalize_job_quota` workflow (guarded by `quota_finalized`, Work +
   Identity in one transaction): success keeps the reservation; failure/cancel refunds
   `reserved − consumed` (clamped ≥ 0).
4. **Audit** — `job.created` / `job.done` / `quota.refund` events land in `audit_events`
   with the scheduling request's `X-Request-ID`.

## Quota semantics per kind

| Kind | Reserve | Consume | On cancel/fail |
|---|---|---|---|
| `codex_build` | 1 up front | 1 on success | full refund |
| `translate` (AGY) | pending-chapter count up front | +1 per chapter **as it actually commits** (inside the `commit_translation` transaction) | refund of the unconsumed remainder — finished chapters stay charged |
| `translate` (API) | availability-check only at scheduling; reserve 1 under each chapter lock | the reserved unit is the charge; failed provider/commit attempts refund it immediately | no batch reservation remains to settle |
| TTS (`tts_jobs`) | none (checked, not reserved) | 1 per chapter **only on actual generation** (cache hits/skips free) | nothing to refund |
| OCR (`ocr_pages`) | via import cost-confirm gate | per page escalated | budget + quota guards; `ocr_paused` on daily-budget exhaustion |
| `scrape` | — | free | — |

## AGY-specific states

An AGY-executed job may enter **`waiting_provider`** (subscription capacity/quota
exhausted): parked with `not_before = now + AGY_PROVIDER_RETRY_MINUTES`, holding **no
lease** and burning no retries; it stays active for dedupe purposes. Release happens
automatically when due, or via the admin "Retry waiting" action. Permanent AGY failure
with fallback allowed re-points the job at the API backend (refunding AGY translation's
unused reservation first). Details: [ai-backends.md](ai-backends.md).

## Observing & operating

- `GET /api/jobs` (+ `/api/jobs/{id}`, `cancel`) — generic jobs, ownership-scoped.
- `GET /api/activity` — all three systems, one feed (the Jobs page + home).
- `GET /api/novels/{id}/cost-estimate` — the pre-spend estimate surface.
- `GET /api/novels/{id}/health` — owner pipeline health incl. recent job errors.
- Admin: platform spend (`GET /api/admin/usage`), AGY health/retry, per-user quota
  overrides.
- Worker liveness: heartbeat visibility is part of the release checklist
  ([../release-runbook.md](../release-runbook.md)).
