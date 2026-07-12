# Pipeline: AI execution backends (API vs AGY)

> Tideglass can execute AI workloads two ways: the metered **API backend** (OpenRouter/
> Gemini, pay-per-token) or the **AGY backend** (the Antigravity CLI, driving a
> subscription account on the host). This page follows one job through backend
> selection, execution, and every failure path. Module reference:
> [../modules/ai-execution.md](../modules/ai-execution.md); operator procedures:
> [../agy-operator-runbook.md](../agy-operator-runbook.md); consistency decision:
> [ADR 003](../architecture/adr-003-ai-scheduling-consistency.md).

## The two backends

| | API | AGY |
|---|---|---|
| Transport | HTTPS to OpenRouter / Gemini | local subprocess: the `agy` CLI in print mode |
| Auth | `OPENROUTER_API_KEY` / `GEMINI_API_KEY` in app env | the CLI's own official browser/keyring login on the host — **never** an app credential |
| Cost model | per-token, metered by user quotas | subscription capacity (rate/quota windows) |
| Executor | in-process (routes, generic worker) | dedicated host worker only (`python -m novelwiki.agy.worker`, systemd) |
| Default | default selection; requires the configured provider credentials | dormant unless `AGY_ENABLED` **and** an admin grant |
| Workloads | all six policy workloads | implemented end-to-end: `translate_batch`, `codex_extract`; policy/schema vocabulary reserves `segment_import`, `ocr_pages`, `ask`, `profile_synthesis` for future routing, but automatic selection keeps them on API and explicit AGY is rejected today |

## Backend selection (at scheduling time)

`resolve_backend(user, workload, requested)` produces an **immutable decision** stamped
onto the job (`execution_backend`, `backend_model`, `backend_policy_version`,
`backend_fallback_allowed`):

1. `requested` is `auto` | `api` | `agy` (UI/API may ask; `auto` follows the user's
   `default_backend`).
2. AGY is chosen only if: `AGY_ENABLED` globally, the user's
   `user_ai_backend_policies` row has `agy_enabled`, the workload is one of
   `IMPLEMENTED_AGY_WORKLOADS`, **and** it appears in `agy_workloads`, and the
   per-user active-AGY-job cap (`max_concurrent_agy_jobs`,
   1–4) isn't exceeded. Otherwise: API (or a typed error if `agy` was demanded
   explicitly).
3. The whole schedule runs inside the `schedule_ai_job` compensation shape:
   reserve quota → create/dedupe job → refund on failure or dedupe.

The decision is *immutable* but execution is *re-authorized*: `reauthorize_job` re-checks
the grant, user status, and `policy_version` **immediately before the AGY subprocess
starts** — revoking a grant or bumping the policy between queue and run wins.

## AGY execution (the hardened path)

The dedicated host worker (never the web process) claims `jobs` rows with
`execution_backend='agy'` via the same atomic `claim_next` primitive:

1. **Preflight** (cached per loop): binary SHA-256 pin (`AGY_BINARY_SHA256`) + minimum
   version + exact model display names present in `agy models` + plugin validation
   (`AGY_PLUGIN_VERSION`/`SHA256`). Any drift ⇒ refuse all work.
2. **Orphan reaping** — kill *identity-verified* stale process groups (pid + start-time
   match from `ai_execution_runs`) before new work.
3. **Workspace** — per-run directory under `AGY_WORK_DIR`: content-hashed input
   manifests (chapters, glossary, rosters — whatever the workload needs), then inputs
   are **sealed read-only**; output/logs stay writable; size-capped.
4. **Run** — `run_agy` spawns the CLI in its own process group with a
   positive-allowlist environment and a print-mode prompt; the repo's AGY plugin
   (`novelwiki-ai`, hooks `tool_gate.py`/`validate_stop.py`) denies command/web/MCP/
   subagent/outside-workspace access from inside the session. Output streams are
   capped; timeout → grace → kill-process-group escalation; cooperative cancel checks.
5. **Validate** — nothing from the model is trusted: artifacts are read via
   `safe_artifact_path` (no traversal), size caps, SHA-256s from the output manifest,
   schema checks, and workload-specific validators (translation quality/glossary
   respect; extraction schema + chunk-id provenance).
6. **Commit** — through the **same workflows** the API path uses
   (`commit_translation`, `commit_codex_extraction`) with run-id identity, so a crashed
   batch can't double-commit and `_resume_ready_commits` can salvage completed
   artifacts without re-running the model.
7. **Record** — every invocation writes an `ai_execution_runs` row (model, attempt,
   input/output hashes, process identity, exit/failure codes, metrics); the worker
   heartbeats `ai_worker_heartbeats` (admin panel turns stale after 90 s).

## Failure taxonomy

| Failure | Handling |
|---|---|
| Provider capacity/quota (codes in `PROVIDER_WAIT_CODES`) | park `waiting_provider`, `not_before = now + AGY_PROVIDER_RETRY_MINUTES` (30); no lease, no tight retries, still dedupes; auto-release when due or admin **Retry waiting** |
| Transient crash | retry up to `AGY_MAX_ATTEMPTS` (2) |
| Permanent failure, `fallback_to_api` allowed | `_fallback_to_api`: job re-pointed to the API backend (`backend_fallback_from='agy'`), AGY translation's unused reservation refunded first so API metering can't double-charge |
| Permanent failure, no fallback | `failed` + quota settlement (refund of unconsumed reservation) |
| Revoked grant / bumped policy at claim time | job not executed (reauthorization loses gracefully) |
| Worker down | jobs queue; startup logs a warning if `AGY_ENABLED` with no healthy heartbeat; kill switch = `AGY_ENABLED=false` (queued AGY jobs stay explicit, spend nothing) |

## Read-side AI (no jobs involved)

Ask and profile synthesis execute inline on the API backend (their AGY policy names are
reserved but not implemented), guarded not by monthly
quota but by the denial-of-wallet gates (verified email; 30 uncached/h; 2 concurrent;
tool-arg clamps) — see
[codex-build-and-ask.md](codex-build-and-ask.md) and AI Execution's
`adapters/outbound/limits.py`.

## Admin surface

`GET/PUT/DELETE /api/admin/users/{id}/ai-backend-policy` (grants are explicit and
per-workload — admin role itself grants nothing), `GET /api/admin/ai/agy/health`,
`POST /api/admin/ai/agy/retry-waiting`, `POST /api/admin/ai/agy/smoke-test`
(a consuming end-to-end test with zero novel/user content). Eval suites:
`eval/agy_{contract,policy,runner,workload}_tests.py` with the `fake_agy.py` binary.
