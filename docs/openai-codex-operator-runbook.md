# OpenAI Codex App Server operator runbook

This optional backend runs translation and NovelWiki Codex extraction against an official
ChatGPT Codex subscription. It is dormant until both the global switch and an explicit
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
enums. The existing safe extraction normalizer also removes unsupported optional state-transition
items before final host validation. Story data is passed as explicitly untrusted task data. The
host—not the model—writes the output files and SHA-256 manifest, after which the existing
translation or extraction validators and atomic commit workflows run.

Workspaces live below `OPENAI_CODEX_WORK_DIR`, outside the checkout and public asset root,
with mode `0700`. Do not point this setting at `ASSET_DIR`, the repository, or a shared path.

## Incidents and rollback

- Stop new work: set `OPENAI_CODEX_ENABLED=false` and restart settings consumers. Queued
  jobs remain explicit and consume nothing.
- Contain extraction only: set `OPENAI_CODEX_CODEX_ENABLED=false`; translation remains
  available.
- Stop the process: `systemctl --user stop novelwiki-openai-codex-worker.service`.
- Provider quota/capacity failures park in `waiting_provider`; use the admin retry action
  after capacity returns.
- Each OpenAI Codex job uses `OPENAI_CODEX_MAX_ATTEMPTS`, independently of the AGY retry
  limit.
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
