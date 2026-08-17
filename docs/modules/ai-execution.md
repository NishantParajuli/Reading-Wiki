# AI Execution module (`novelwiki/modules/ai_execution/`)

**Responsibility:** *how* AI work runs, as opposed to *what* it does. This module owns:
the provider gateways (native DeepSeek/OpenRouter chat, OpenRouter embeddings/rerank,
Gemini vision), the read-side
**cost controls** (denial-of-wallet guards on Ask/profile synthesis), the admin-granted
**backend policy** deciding whether a user's job runs on the metered **API**, the
subscription-based **AGY CLI**, or **OpenAI Codex App Server**; the hardened isolated
runners/workspaces/validators; dedicated host workers; per-invocation **run records**;
and worker **heartbeats**.
Backend selection end-to-end: [../pipelines/ai-backends.md](../pipelines/ai-backends.md).
Operator procedures: [../agy-operator-runbook.md](../agy-operator-runbook.md) and
[../openai-codex-operator-runbook.md](../openai-codex-operator-runbook.md).

**Owned tables:** `user_ai_backend_policies`, `ai_request_locks`, `provider_budget`,
`ai_execution_runs`, `ai_worker_heartbeats`.

---

## Public contract (`public.py`)

- **Gateways** (`Protocol`s other modules' runtimes receive): `ChatGateway.complete`,
  `EmbeddingGateway.embed`, `RerankGateway.rerank`, `VisionGateway.inspect`.
- **Domain types** (`domain/backend.py`): `Workload` (the six policy-vocabulary workloads:
  `translate_batch`, `codex_extract`, `segment_import`, `ocr_pages`, `ask`,
  `profile_synthesis`), `RequestedBackend` (`auto`/`api`/`agy`/`openai_codex`),
  `ExecutionBackend` (`api`/`agy`/`openai_codex`). The two subscription adapters currently
  implement `translate_batch` and `codex_extract`; extraction additionally requires that
  provider's default-off Codex kill switch. For the other four workloads, selection remains
  on API and an explicit subscription request is rejected even if the policy stores the name.
- **Contracts** (`application/contracts.py`): the shared subscription-run manifest dataclasses —
  `InputManifest`/`OutputManifest`/`ArtifactRef`, `ExtractionPayload`,
  `DisambiguationPayload`, `TranslationMeta`, `PreflightResult`.
- **Errors** (`application/errors.py`): `AgyError`, `AgyPreflightError`,
  `AgyValidationError`, `AgyCanceled`, `BudgetExhausted`, and `PROVIDER_WAIT_CODES`
  (failure classes that park a job as `waiting_provider` instead of burning retries).
- **`ResumableRunQuery`** — lets codex/translation find complete-but-uncommitted run
  artifacts after a crash and obtain a job's run IDs without reading AI Execution's table
  across the module boundary.

## Outbound adapters

### `providers.py` — the API backend

Implementations of the four gateways. Text generation uses native DeepSeek for the V4
model ids when `DEEPSEEK_API_KEY` is non-empty, otherwise OpenRouter; non-DeepSeek model
ids remain on OpenRouter. Embeddings (`EMBED_MODEL`, `EMBED_DIM`,
`EMBED_REQUEST_DIMENSIONS`) and reranking (`RERANK_MODEL`) always use OpenRouter. Gemini
vision uses its OpenAI-compatible endpoint with the persistent **daily budget**
(`provider_budget` rows per (provider, day), `GEMINI_DAILY_BUDGET`, `GEMINI_RPM`) so a
multi-day OCR run can't blow the free tier after a restart.

### `limits.py` — read-side cost controls

Uncached AI *reads* (Ask, entity-profile synthesis) fan out to embeddings + rerank +
multiple model calls, so they're gated like costed writes:
`require_ask_spend_allowed` (verified email or admin → else 403),
`consume_ask_rate` (fixed window, `ASK_MAX_UNIQUE_PER_USER_HOUR`=30 uncached reads/h →
429), and `concurrency_slot` (at most `ASK_MAX_CONCURRENT_PER_USER`=2 in flight, backed
by self-expiring `ai_request_locks` rows with a `ASK_CONCURRENCY_TTL_SECONDS`=180 lease
so a crashed request frees its slot). **Cache hits skip every gate.**
These controls bound spend; Codex owns the separate quality boundary. An uncached Ask is
cacheable only after its verifier and deterministic retrieved-evidence citation checks pass,
while entity prose is cacheable only after profile verification/repair and model/version checks.

### `policy.py` — grants and backend resolution

- `user_ai_backend_policies` is **admin-owned** (no row ⇒ API-only; only admin routes
  mutate it): provider enable switches/workload arrays/concurrency caps for AGY and OpenAI
  Codex, `default_backend`, shared `fallback_to_api`, `policy_version` (bumped on every
  change), `granted_by`, `notes`.
- `resolve_backend(user, workload, requested, *, enforce_concurrency)` → an immutable
  per-job decision (backend, model, policy version, fallback allowance) applied at
  scheduling time; `reauthorize_job(job, user)` re-checks the grant/status **again just
  before a subscription subprocess starts** (a revoked grant between queueing and execution
  loses); `worker_available()` treats a recent heartbeat as a *capability signal, never
  an entitlement*; `capability_for_user` feeds the `/auth/me` UI capabilities.

### `agy/` — the hardened CLI runner

- **`preflight.py`** — refuses to run unless: the binary at `AGY_BINARY` matches
  `AGY_BINARY_SHA256`, version ≥ `AGY_MIN_VERSION`, the exact configured model display
  names exist in `agy models`, and an isolated copied plugin validates and appears in
  `agy plugin list` (`AGY_PLUGIN_VERSION`/`AGY_PLUGIN_SHA256`).
- **`workspace.py`** — one directory per run under `AGY_WORK_DIR`
  (`~/.local/share/novelwiki/agy-jobs`, outside the checkout and outside public asset
  roots) and a sibling isolated CLI state. It links the validated official credential
  files without loading token contents, writes a run-only settings file (`accept-edits`,
  `strict`, `always-proceed`, and only that trusted workspace), materializes hash-pinned
  hooks/rules under `.agents`, creates the Git marker AGY 1.1.2 requires for discovery, and seals
  inputs/customizations/Git metadata read-only. Output/logs remain writable, with size caps
  (`AGY_WORKSPACE_MAX_BYTES`) and retention sweeps
  (`AGY_SUCCESS_RETENTION_HOURS`=24 / `AGY_FAILURE_RETENTION_HOURS`=168).
- **`runner.py`** — spawns the CLI in its own **process group** with a positive-allowlist
  environment, print-mode prompt, output caps (`AGY_STDOUT/STDERR_MAX_BYTES`), timeout +
  grace + kill escalation (`AGY_PRINT_TIMEOUT_SECONDS`/`_OUTER_TIMEOUT_GRACE`/
  `_KILL_GRACE`), cancel checks, identity-verified process-group termination,
  runtime proof that exactly the pinned two hooks loaded from one file, and hard ceilings for model requests, hook failures,
  and consecutive planner warnings without output-tree progress
  (`process_identity_matches` guards against PID reuse).
- **`validators.py`** — every artifact read back is size-capped, SHA-256-verified,
  path-traversal-safe (`safe_artifact_path`), and schema-checked against the output
  manifest.
- **`errors.py`** — stderr/exit-code classification into retryable / provider-wait /
  fatal; `safe_error_summary` keeps story text out of error strings.
- **`runs.py`** — `ai_execution_runs` bookkeeping: one row per provider invocation
  (workload, backend, model, attempt, input/output SHA-256s, workspace relpath, process
  identity, exit/failure codes, metrics including AGY model requests/tool confirmations/
  sandbox blocks/hook state/planner defects; provider token usage is explicitly marked
  unavailable; linked to exactly one of `job_id` /
  `import_job_id`, with `parent_run_id` for disambiguation/verification child runs).
- **`smoke.py`** — the admin smoke test (`kind='agy_smoke'` job; no novel/user content).
- **`prompts.py`** — inlines the hash-pinned workload instructions into the initial print
  prompt. This avoids AGY 1.1.2's workspace-skill activation loop and redundant discovery
  turns; Codex supplies one bounded-memory `input/task.md` bundle with strict extraction
  artifact schema 2.2, verbatim per-claim evidence anchors, and exact distributed-coverage
  reducer targets, while disambiguation inlines its complete decision
  object and supplied-candidate rule. The trusted stop hook creates the final manifest after
  the model writes only its semantic artifacts and validates exact disambiguation case
  coverage before allowing the child run to stop.
- **`plugin/novelwiki-ai/`** (repo path `novelwiki/agy/plugin/novelwiki-ai`) — the AGY
  plugin whose hooks (`tool_gate.py`, `validate_stop.py`) deny command/web/MCP/subagent
  and outside-workspace access from inside the CLI session; its file hashes are pinned
  in the contract snapshot.

### `worker_state.py`

Subscription-worker persistence: provider-keyed heartbeat writes (`ai_worker_heartbeats`
— status, versions, contract/plugin hash, details; provider-specific health TTL drives the
admin panel and `/auth/me` capability), orphan-run detection, resumable-run queries.

### `openai_codex/` — official App Server adapter

- **`preflight.py`** pins the official binary/version/hash, verifies an official ChatGPT
  account with `account/read`, and confirms configured Terra/Luna models via `model/list`
  without starting a consuming turn.
- **`client.py`** implements bounded JSONL stdio for `initialize`, `thread/start`, and
  `turn/start`; it enforces an ephemeral thread, never-approve policy, read-only/no-network
  sandbox, cancellation/interrupt, process identity, stream limits, and token-usage metrics.
- **`contracts.py` / `runner.py`** supply strict workload JSON Schemas. The host parses the
  final structured message, injects sealed-input identity into extraction artifacts, and
  materializes the same hashed translation/extraction/disambiguation artifacts expected by the
  existing validators; the shared validation path then applies loss-minimizing grounded
  normalization, retaining only trusted ids from mixed chunk provenance while rejecting
  all-unsupplied provenance. The model never writes files.
- **`workspace.py`** creates the private run root and isolated sibling `CODEX_HOME`, linking
  only the official `auth.json` while disabling persisted history and web search.
- **`smoke.py`** implements the explicitly consuming, rate-limited admin readiness turn and
  always terminalizes its run record as completed, failed, or canceled with `finished_at`.

## The dedicated host worker (`adapters/inbound/worker.py`)

Subscription execution runs **only** in separate host processes: AGY via
`python -m novelwiki.agy.worker`, and OpenAI Codex via
`python -m novelwiki.openai_codex.worker`. Each has its own systemd unit, advisory lock,
heartbeat, queue backend, credential state, and global kill switch. The AGY unit is
`deploy/novelwiki-agy-worker.service`; both units run under the OS user that completed
the corresponding official login, and the web/API worker never touches either CLI. Loop:
preflight → heartbeat task → **reap verified orphan process groups** → claim
(`claim_next` with the process's provider backend, gated by its global switch and
per-user concurrency) → `_reauthorize` → dispatch to provider codex/translation handlers →
on provider-capacity failures park as `waiting_provider`
(provider-specific retry interval); on permanent failure with `fallback_to_api` allowed,
`_fallback_to_api` re-points the job at the API backend (refunding the subscription
backend's unused translation reservation first). Attempts use the provider-specific cap.

## Admin surface

Mounted in Experience's admin router, executed here through injected ports:
`GET/PUT/DELETE /api/admin/users/{id}/ai-backend-policy`, `GET /api/admin/ai/agy/health`,
`POST /api/admin/ai/agy/retry-waiting`, `POST /api/admin/ai/agy/smoke-test`; equivalent
OpenAI Codex operations are under `/api/admin/ai/openai-codex/`.

## Design invariants

1. **Dormant by default** — each subscription provider requires its global switch *and* an
   explicit per-user workload grant for one of its two implemented workloads; extraction
   additionally requires that provider's Codex switch. Neither a role nor one switch alone suffices.
   Admin role grants nothing implicitly.
2. **No subscription credentials in settings or PostgreSQL** — authentication belongs to
   each official CLI login owned by its host service account.
3. **Immutable decisions, revocable execution** — backend decisions are stamped on the
   job; execution re-authorizes; policy bumps (`policy_version`) invalidate stale queued
   decisions.
4. **Nothing from the model is trusted** — sealed inputs, allowlisted env, validated
   artifacts, capped outputs, classified failures.
