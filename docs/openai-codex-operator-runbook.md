# OpenAI Codex App Server operator runbook

This optional backend runs translation, NovelWiki Codex extraction, and opt-in chapter
illustrations against an official ChatGPT Codex subscription. It is dormant until both the global switch and an explicit
per-user workload grant are enabled. It does not use `OPENAI_API_KEY` and never copies a
ChatGPT token into NovelWiki settings or PostgreSQL.

## Install and authenticate

1. Install the official Codex CLI for the OS user that will run the worker. The tested
   minimum is `codex-cli 0.146.0`.
2. Put a stable executable at the configured path, for example:

   ```bash
   mkdir -p ~/.local/bin
   ln -s "$(command -v codex)" ~/.local/bin/codex
   codex --version
   sha256sum "$(readlink -f ~/.local/bin/codex)"
   ```

3. Run `codex login` as that same OS user and choose ChatGPT authentication. Keep
   `~/.codex/auth.json` owned by that user with mode `0600`. NovelWiki validates the file
   metadata but does not parse or log its contents.
4. Copy the OpenAI Codex settings from `.env.example`. Its `~/.local/...` and `~/.codex`
   values resolve against the OS account that runs the worker, matching the `%h` systemd
   paths; no sample username needs replacement. Set the binary hash to the hash from step 2.
   Keep both enable switches false initially.
5. Run the non-consuming preflight:

   ```bash
   uv run python -m novelwiki.modules.ai_execution.adapters.outbound.openai_codex.preflight
   ```

   Healthy output confirms the binary/version/hash, ChatGPT account type, App Server
   initialization, and configured model catalog. It does not start a model turn.

## Start and canary

Install the dedicated user service:

```bash
install -m 0644 deploy/novelwiki-openai-codex-worker.service \
  ~/.config/systemd/user/novelwiki-openai-codex-worker.service
systemctl --user daemon-reload
systemctl --user enable --now novelwiki-openai-codex-worker.service
journalctl --user -u novelwiki-openai-codex-worker.service -f -o cat
```

The checked-in unit sets `HOST_WORKER_DATABASE_HOST=127.0.0.1`. This lets the host worker
reuse the Docker-oriented `.env` URLs containing `host.docker.internal` without copying
database credentials or changing the web container's connection target.

Set `OPENAI_CODEX_ENABLED=true` and restart the web and dedicated worker. The admin health
panel must show a recent healthy heartbeat. Use the admin **Run consuming smoke test** button
once; it deliberately starts a small model turn and is rate-limited to one per ten minutes.
Every smoke invocation leaves a terminal `completed`, `failed`, or `canceled`
`ai_execution_runs` row with `finished_at`, failure metadata, and any available process
metrics, so the admin failure projection and retention sweep can account for it.
Only after that succeeds should an admin grant `translate_batch` to a pilot user. Enable
`OPENAI_CODEX_CODEX_ENABLED=true` separately before granting `codex_extract`.

The supported quality/latency policy is enforced at application startup: high-volume Codex,
verification, disambiguation, and smoke workloads use `gpt-6-luna` at `xhigh`; translation
uses `gpt-5.6-terra` at `xhigh`. Luna is the preferred/default Codex role. An environment
override that selects Luna/Terra with weaker effort is rejected. GPT-6 Luna additionally
accepts `max` for an explicit deeper-reasoning configuration; legacy Luna/Terra retain
their `xhigh` policy. Production Codex builds also
run the separate Luna/xhigh verification child by default.

## Recover after a Codex CLI update

An npm/CLI update can change the executable behind `OPENAI_CODEX_BINARY` while leaving its
configured SHA-256 pin unchanged. The dedicated service can remain running but its
preflight reports `openai_codex_version_unsupported` with a hash-mismatch message; it
does not claim extraction, translation, or illustration jobs while unhealthy.

Verify the intended official installation with `codex --version` and
`sha256sum "$(readlink -f ~/.local/bin/codex)"`. Update
`OPENAI_CODEX_BINARY_SHA256` in the deployment environment to the verified new digest,
then run the non-consuming preflight above. Keep the pin enabled. Restart
`novelwiki-openai-codex-worker.service` after preflight passes so the process loads the
updated configuration. When changing a model or other shared settings, also recreate
the web container with the updated environment. Confirm a fresh healthy heartbeat
before requesting new work; restarting a healthy worker can resume already queued jobs.

## Extraction contract

Extraction contract `1.3.10` emits artifact schema `2.2`. Every material claim carries a short
contiguous verbatim `evidence_text` anchor from one cited current-chapter chunk. The host proves literal
locality using exact source-word sequences independent of punctuation and dialogue typography;
changed words or word order still fail. The independent verifier checks whether that evidence semantically entails the
reader-facing claim and receives targeted group/index repair instructions for malformed draft
anchors. A final verifier anchor that selects exact source words in order but omits a bounded
intervening span is canonicalized to the complete contiguous source passage. An otherwise exact
anchor citing an adjacent overlapping chunk is relocated to the supplied chunk containing it.
This verified-only repair is capped at 32 inserted tokens, 24 tokens in any one gap, three-times
expansion, and 1,200 source characters; changed/reordered words and distant stitching still reach
quarantine or broad-failure handling. Claim/ref alignment accepts safe regular plurals for concept and item names plus a
whole-name possessive-number variant for organization/category names, not prefix, stem, or fuzzy
matches. First-pass duplicate plot-thread updates are sent to the independent verifier as exact
repair targets instead of failing before review. The final artifact still permits only one update
per thread and chapter; one isolated leftover duplicate is quarantined, while broader duplication
retries the chapter. The same bounded quarantine applies to isolated residual evidence or alignment
items. A first-pass plot-thread topic miss also reaches the verifier instead of failing on exact
stable-title vocabulary. The verifier may retain one semantic alias/persona/paraphrase match only
when the update preserves strong trusted-participant continuity; multiple misses or weak continuity
fail with `thread_relevance_broad_failure`. Dormant threads still require an explicit `reopen`.
The atomic database commit replays the same bounded verified policy; it does not fall back to the
pre-verification lexical-only gate.
Broad grounding or alignment failure still rejects the chapter with an explicit recovery code. This contract changes no
persisted Codex table shape and does not invalidate already committed pipeline-2.1 chapters.
Primary extraction remains under `CODEX_CONTEXT_MAX_TOKENS` (48k). Verification serializes the
complete draft as compact JSON and uses the separate `CODEX_VERIFY_CONTEXT_MAX_TOKENS` (64k)
ceiling because its input necessarily contains primary context plus that draft. Neither source,
memory, nor claims are truncated. A true overflow reports `codex_context_budget_exceeded` rather
than the misleading generic artifact-invalid code. Sealed input manifests record both
`limits.task_tokens` and `limits.max_task_tokens` for direct operator diagnosis.

## Security and data boundary

Every invocation receives a new sibling `CODEX_HOME`. It contains a read-only symlink to the
official `auth.json`, disables web search and persisted history, and is deleted by retention
cleanup with the run. App Server uses stdio, `approvalPolicy=never`, a read-only sandbox, no
network tool access, no MCP/apps/plugins/subagents, an ephemeral thread, and a strict JSON
output schema. The host converts every Pydantic model to the Structured Outputs subset before
starting a turn: every object rejects additional properties, every declared property is required,
nullable fields remain nullable, model-side defaults are removed, and otherwise unconstrained
state values are bounded to JSON scalars or scalar arrays. Validator-owned vocabularies (entity
types, state keys, relationship-state keys, and translation term types) are emitted as schema
enums. The safe extraction normalizer removes unsupported optional state-transition items. For
extraction, the host injects the trusted chapter number and source hash from the sealed inputs; it
also removes nonliteral new-mention records and only claims that depend on those local refs. Mixed
provenance retains supplied chunk ids and drops unsupplied ids, while all-unsupplied provenance
still fails closed before strict validation of everything retained. Story data is passed as
explicitly untrusted task data. The host—not the model—writes the output files and SHA-256
manifest, after which the existing
translation or extraction validators and atomic commit workflows run.

Workspaces live below `OPENAI_CODEX_WORK_DIR`, outside the checkout and public asset root,
with mode `0700`. Do not point this setting at `ASSET_DIR`, the repository, or a shared path.

## Native chapter illustrations

The reader's opt-in illustration control and Manage's **Illustrate ahead** range control
schedule `codex_illustrate` on this worker. A range is one durable job over up to 1,000
translated story chapters, processed sequentially with per-chapter checkpoints.
It shares the `codex_extract` grant and `OPENAI_CODEX_CODEX_ENABLED` switch, requires
owner/admin edit access, and uses the connected ChatGPT subscription for both art planning
and native image generation. It never uses an image API key or falls back to metered API
generation. No monthly Codex-build unit is reserved.

The initial context decision, illustration planner, and rendering turns are fixed to
`gpt-6-luna` with `max` reasoning, independently of the ordinary extraction model/effort
settings. Before each
operation the renderer confirms Luna is available and its model catalog advertises MAX.
A missing model/effort fails explicitly rather than silently selecting a different model.
The native-image turn remains isolated and stops at the first completed image event;
translation and extraction retain their existing tool-free structured-output contract.

For rollout, start with one short, already readable shared chapter. AI selects one to
three scene images; new character sheets can add up to four image turns per chapter.
Two tool-free planning stages first decide whether recent context is needed, then plan
scenes. Each stage can make up to two additional correction turns when host validation
rejects a response. `illustration_plan_invalid` includes a safe validation reason, such
as a scene quotation absent from the chapter; it does not contain the chapter text or
raw provider response. Corrections preserve exact-evidence and placement requirements.
If corrections are exhausted, normal job retries apply and completed chapter art is
retained. Jobs reports the chapter and correction stage for a range. After deploying a
worker fix, restart `novelwiki-openai-codex-worker.service`. For a terminally failed range,
request the same range again in Manage with replacement disabled; complete current art
is skipped and eligible character sheets are reused. Automatic retries of an existing
job resume its saved plans and image slots. The admin **Retry waiting** action applies
only to jobs in `waiting_provider`, not terminal failures.

Use Jobs for progress/cancellation; canceling retains completed images.
Image quota failures and completed turns with no image park in `waiting_provider`;
restore capacity before retrying quota failures. Chapter/source changes
require a fresh request instead of publishing stale images. These limits and the reader
workflow are detailed in [chapter illustrations](pipelines/chapter-illustrations.md).

PNG bytes are stored in PostgreSQL (`codex_art`), up to 16 MiB per image; account for
them in database backup/storage sizing. They are served through authenticated chapter-
bounded endpoints with private no-store caching. Temporary native-image workspaces and
their isolated `CODEX_HOME` are removed after each operation; the durable plan, images,
and safe execution status remain in the database.

## Incidents and rollback

- Stop new work: set `OPENAI_CODEX_ENABLED=false` and restart settings consumers. Queued
  jobs remain explicit and consume nothing.
- Contain extraction and illustration generation: set `OPENAI_CODEX_CODEX_ENABLED=false`; translation remains
  available.
- Stop the process: `systemctl --user stop novelwiki-openai-codex-worker.service`.
- Provider quota/capacity failures park in `waiting_provider`; use the admin retry action
  after capacity returns.
- Each OpenAI Codex job uses `OPENAI_CODEX_MAX_ATTEMPTS`, independently of the AGY retry
  limit.
- Drain or cancel active model turns before activating a new extraction contract. Uncommitted
  artifact-schema 2.1 runs cannot resume under contract 1.3.3 or later; committed pipeline-2.1 chapters
  remain valid checkpoints.
- Failed turns classify only App Server's protocol-defined `codexErrorInfo` tag and optional
  HTTP status. JSON-RPC request rejections also recognize structured error metadata, 401/403,
  and a small authentication/permission marker allowlist. Only the resulting safe category
  appears in run summaries; raw provider messages remain excluded because they may contain
  submitted story text.
- Authentication or permission rejection during `thread/start`/`turn/start`, as well as
  version/model/protocol drift, makes the worker unhealthy, parks the current job, and stops
  new claims. Re-authenticate or correct the policy, then re-run preflight before re-enabling.
- Revoking a user's grant cancels queued work and is checked again immediately before each
  subprocess starts.
- Roll back the application and schema together using the normal release runbook. Existing
  `openai_codex` job/run rows remain auditable even while the backend is disabled.
