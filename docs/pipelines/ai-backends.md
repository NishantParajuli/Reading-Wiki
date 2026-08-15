# Pipeline: AI execution backends (API, AGY, OpenAI Codex)

> Tideglass can execute AI workloads through the metered **API backend** or two isolated
> host subscription workers: **AGY** (Antigravity) and **OpenAI Codex App Server** (ChatGPT).
> This page follows one job through backend
> selection, execution, and every failure path. Module reference:
> [../modules/ai-execution.md](../modules/ai-execution.md); operator procedures:
> [../agy-operator-runbook.md](../agy-operator-runbook.md) and
> [../openai-codex-operator-runbook.md](../openai-codex-operator-runbook.md); consistency decision:
> [ADR 003](../architecture/adr-003-ai-scheduling-consistency.md).

## The three backends

| | API | AGY | OpenAI Codex |
|---|---|---|---|
| Transport | HTTPS to DeepSeek / OpenRouter / Gemini | local `agy` print subprocess | local `codex app-server` JSONL over stdio |
| Auth | provider keys in app env | official Antigravity host login | official `codex login` ChatGPT session; no API key |
| Cost model | per-token, metered by user quotas | subscription capacity | ChatGPT Codex subscription capacity |
| Executor | in-process routes/generic worker | `python -m novelwiki.agy.worker` | `python -m novelwiki.openai_codex.worker` |
| Default | available when keys are configured | dormant unless global switch + grant | dormant unless global switch + grant |
| Workloads | all six policy workloads | `translate_batch`, `codex_extract` | `translate_batch`, `codex_extract` |

### Codex equivalence and call topology

For `codex_extract`, backend choice changes transport and provider-call shape, not the
stored meaning or integrity boundary:

| Property | API | AGY | OpenAI Codex |
|---|---|---|---|
| Context and proposal | shared deterministic bounded context and v2.1 schema | same | same |
| Review | optional best-effort second call, default on via `EXTRACTION_VERIFY` | mandatory self-review in the primary artifact run; optional separate child via `AGY_SEPARATE_CODEX_VERIFY` | strict structured primary result plus a default independent Luna/xhigh verification child via `OPENAI_CODEX_SEPARATE_CODEX_VERIFY` |
| Chapter summary | separate API call | emitted with the reviewed extraction artifacts | emitted with the structured extraction result |
| Ambiguous linking | direct per-mention gray-case calls when needed | gray cases batched into one disambiguation child run | same batched disambiguation contract |
| Validation and storage | trusted proposal/provenance/ref validation, then source/context-checked atomic commit | same semantic validators and the same `commit_codex_extraction` workflow | same semantic validators and workflow |

Model output is still nondeterministic, so two backends need not produce byte-identical
claims. They are required to obey the same ceiling, memory, provenance, temporal, and
commit contract.

## Backend selection (at scheduling time)

`resolve_backend(user, workload, requested)` produces an **immutable decision** stamped
onto the job (`execution_backend`, `backend_model`, `backend_policy_version`,
`backend_fallback_allowed`):

1. `requested` is `auto` | `api` | `agy` | `openai_codex` (UI/API may ask; `auto` follows the user's
   `default_backend`).
2. A subscription backend is chosen only if its global switch is enabled, its independent
   Codex-extraction switch is enabled for `codex_extract`, its per-user provider grant includes
   the workload, the adapter implements it, and that provider's 1–4 active-job cap is not
   exceeded. Otherwise `auto` resolves to API; an explicit unavailable provider returns a typed
   error.
3. The whole schedule runs inside the `schedule_ai_job` compensation shape:
   reserve quota → create/dedupe job → refund on failure or dedupe.

The decision is *immutable* but execution is *re-authorized*: `reauthorize_job` re-checks
the grant, user status, and `policy_version` **immediately before the subscription subprocess
starts** — revoking a grant or bumping the policy between queue and run wins for either worker.

## OpenAI Codex App Server execution

The dedicated OpenAI Codex worker claims only `execution_backend='openai_codex'` rows and holds
its own advisory subscription lock. Preflight pins the official executable/version, verifies a
ChatGPT account through `account/read`, and confirms Terra/Luna in `model/list` without starting a
turn. Each run gets a sealed workspace plus isolated `CODEX_HOME`; only the official `auth.json`
is linked. History and web search are disabled.

The worker starts an ephemeral App Server thread with `approvalPolicy=never`, read-only sandbox,
network disabled for the sandbox, no interactive client actions, and a workload-specific JSON
Schema normalized to OpenAI's strict Structured Outputs subset (all properties required,
`additionalProperties=false` for every object, nullable types preserved, defaults removed, and
otherwise unconstrained transition values bounded to JSON scalars or scalar arrays). Closed host
vocabularies are emitted as enums, and the same loss-minimizing extraction normalization used by
AGY runs before final Pydantic validation. The host injects extraction chapter/source identity from
the sealed inputs and removes nonliteral new mentions together with only claims that depend on
those refs. For mixed provenance it keeps only supplied chunk ids; an item with no supplied chunk
id still fails closed, and all retained shapes and references remain strict. Story content is
passed inside an explicit untrusted-data boundary. The model cannot write files: the host validates
the final structured message, writes the exact artifact files and SHA-256 manifest, then enters the
same validators, resumable-commit logic, quota settlement, and atomic database workflows as AGY.
Cancellation sends
`turn/interrupt` and then identity-checked process-group termination. Token usage notifications are
stored as run metrics; failed turns retain only an allowlisted App Server error tag/HTTP status,
and request-level authentication/permission rejections are reduced to safe worker-health
categories. Raw App Server messages and story/transcript content are not written to logs.

## AGY execution (the hardened path)

The dedicated host worker (never the web process) claims `jobs` rows with
`execution_backend='agy'` via the same atomic `claim_next` primitive:

1. **Preflight** (cached per loop): binary SHA-256 pin (`AGY_BINARY_SHA256`) + minimum
   version + exact model display names present in `agy models` + a plugin copied into a
   disposable isolated CLI state, validated and confirmed by `agy plugin list`
   (`AGY_PLUGIN_VERSION`/`SHA256`). Any drift ⇒ refuse all work.
2. **Orphan reaping** — kill *identity-verified* stale process groups (pid + start-time
   match from `ai_execution_runs`) before new work.
3. **Workspace** — per-run directory under `AGY_WORK_DIR` plus a sibling per-run CLI
   state directory: content-hashed input manifests (Codex packs chapter, strict v2.1 schema,
   and bounded memory into one `input/task.md` read turn; translation likewise bundles its glossary and
   sub-batch), direct `.agents` customizations and a minimal Git marker required
   by AGY 1.1.2, then inputs/customizations/Git metadata are **sealed read-only**;
   output/logs stay writable; size-capped.
4. **Run** — `run_agy` spawns the CLI in its own process group with a
   positive-allowlist environment and a print-mode prompt; the repo's AGY plugin
   (`novelwiki-ai`, hooks `tool_gate.py`/`validate_stop.py`) denies command/web/MCP/
   subagent/outside-workspace access from inside the session. Output streams are
   capped. The runner parses metadata-only CLI log telemetry and fails closed if either
   pinned hook is absent or an unexpected hook is present, a hook fails, model requests exceed 16, or more than 10
   planner warnings occur without output-tree progress; timeout → grace → kill-process-group
   escalation remains the outer bound. Successful AGY 1.1.2 tool steps can emit the same
   planner warning, so its total alone is not an error. AGY token totals are unavailable in
   print mode.
5. **Validate** — nothing from the model is trusted: artifacts are read via
   `safe_artifact_path` (no traversal), size caps, SHA-256s from the output manifest,
   schema checks, and workload-specific validators (translation quality/glossary
   respect; extraction schema + chunk-id provenance; exact batched-disambiguation case
   coverage and supplied-candidate decisions). The stop hook performs the same
   disambiguation shape/candidate checks early so malformed output gets its bounded repair
   turn before process exit.
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
| Provider capacity/quota | park `waiting_provider` for the selected provider's retry interval; no lease or tight retry; auto-release when due or admin **Retry waiting** |
| Transient crash | retry up to the selected subscription backend's max attempts (2 by default) |
| Authentication/permission rejection | mark that subscription worker unhealthy, park the current job, and stop new claims until operator recovery |
| Permanent failure, `fallback_to_api` allowed | `_fallback_to_api`: job re-pointed to the API backend with the selected provider in `backend_fallback_from`; its unused translation reservation is refunded first so API metering cannot double-charge |
| Permanent failure, no fallback | `failed` + quota settlement (refund of unconsumed reservation) |
| Revoked grant / bumped policy at claim time | job not executed (reauthorization loses gracefully) |
| Codex kill switch off | `codex_extract` is rejected at scheduling and again before subprocess launch; translation remains independently available |
| Missing/failed AGY hooks | terminate AGY immediately with a permanent plugin/hook failure |
| Planner responses without output progress | reset the streak whenever the output tree changes; terminate only after the configured no-progress threshold with `agy_planner_loop` |
| Model-request ceiling | terminate with `agy_request_limit` before an unbounded agent loop can consume more capacity |
| Worker down | provider-specific jobs queue; disabling that provider's global switch prevents claims and spend |

## Read-side AI (no jobs involved)

Ask and profile synthesis execute inline on the API backend (their subscription policy names are
reserved but not implemented), guarded not by monthly
quota but by the denial-of-wallet gates (verified email; 30 uncached/h; 2 concurrent;
tool-arg clamps). Ask then requires verifier + deterministic retrieved-evidence citation checks;
profile prose requires verifier/repair + machine-valid evidence ids. Failed grounding returns a
safe uncached Ask response or fails profile synthesis without populating its cache — see
[codex-build-and-ask.md](codex-build-and-ask.md) and AI Execution's
`adapters/outbound/limits.py`.

## Admin surface

`GET/PUT/DELETE /api/admin/users/{id}/ai-backend-policy` (provider grants are explicit and
per-workload — admin role itself grants nothing). Each provider has health, retry-waiting, and
consuming smoke-test routes below `/api/admin/ai/agy/` or `/api/admin/ai/openai-codex/`.
The smoke tests contain no novel/user content. Eval suites:
`eval/agy_{contract,policy,runner,workload}_tests.py` with the `fake_agy.py` binary, plus
provider-free App Server protocol/materialization unit tests.
