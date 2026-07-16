# NovelWiki Antigravity worker

The web/API worker remains universal. AGY runs only in this separate host service under the
OS user that completed the official AGY browser/keyring login.

## Enable

1. Confirm `agy --version` is at least 1.1.2 and `sha256sum ~/.local/bin/agy` matches
   `AGY_BINARY_SHA256`.
2. Confirm the exact configured model names appear in `agy models`.
3. Validate the plugin:
   `agy plugin validate novelwiki/agy/plugin/novelwiki-ai`.
4. Complete official AGY sign-in. Keep its files in `AGY_CREDENTIAL_DIR`, owned by the
   service user; the OAuth token must be mode 0600. NovelWiki creates a separate CLI state
   directory for every run, so mutable CLI/plugin state is never shared between jobs.
5. Run the authenticated canary (it consumes provider capacity):

   ```bash
   export TEST_DATABASE_URL=postgresql://test-user:password@127.0.0.1:5432/novelwiki_test
   export TEST_DB_SUPERUSER_URL=postgresql://test-admin:password@127.0.0.1:5432/postgres
   RUN_REAL_AGY_TESTS=1 uv run pytest -q novelwiki/eval/agy_real_cli_tests.py -m agy_real
   ```

   The eval safety fixture creates and drops a random disposable database even though this
   canary itself does not use application data; never point those variables at production.

   The canary passes only when AGY completes the contracted write, the trusted stop hook
   creates a valid manifest, both safety hooks are observed in the CLI log, and the model
   request ceiling is respected. AGY 1.1.2 also emits
   `PlannerResponse without ModifiedResponse encountered` for successful file-tool steps;
   NovelWiki therefore treats only consecutive warnings **without output progress** as a
   stall.
6. Verify sandbox/permission rules deny command, web, MCP, subagent, and outside-workspace access.
7. Set `AGY_ENABLED=true`, install `deploy/novelwiki-agy-worker.service` under
   `~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now novelwiki-agy-worker`.
8. Run a non-committing Codex canary against the intended chapters (this reads novel data and
   consumes provider capacity, but deletes its private workspace and never writes Codex rows):

   ```bash
   uv run python scripts/diagnose_agy_codex.py --novel-id 33 \
     --chapter 1 --chapter 2 --chapter 3 --chapter 4 --chapter 5
   ```

   Repeated `--chapter` flags share one preflight. On 2026-07-15, pinned AGY 1.1.2 completed
   Lord of the Mysteries chapters 1–5 with `6, 6, 6, 7, 7` model requests, one or two reads,
   exactly three writes, valid provenance contracts, and no hook/sandbox failure. The generic
   smoke fell from 12 requests to 3 after removing skill activation and redundant file turns.
9. Use the admin Antigravity health panel, then explicitly grant one owner the intended
   workload. `AGY_CODEX_ENABLED` remains default-off for controlled rollout; enable it only
   after the pinned smoke and representative Codex canaries pass. Do not infer access from
   admin role.

AGY 1.1.2 discovers workspace `.agents/hooks.json` and rules only when the run
directory is a Git project. NovelWiki therefore creates a minimal sealed `.git` marker and
materializes the hash-pinned plugin in `.agents/vendor/novelwiki-ai`. `agy plugin list` is a
preflight registry check, not proof that print mode activated hooks; runtime log telemetry is
the activation proof. Workspace skills are intentionally not exposed to print mode: AGY 1.1.2
can loop while activating them. The same hash-pinned workload body is inlined into the trusted
initial prompt, exact Codex inputs are bundled into `input/task.md`, and the stop hook writes
the output manifest so the model does not waste turns listing, verifying, or hashing files.

Use `loginctl enable-linger <user>` if the user service must survive logout. The service must
retain access to the authenticated user's DBus/keyring session.

## Codex v2 rollout

The bundled NovelWiki plugin contract is version `1.3.1` and emits Codex schema `2.0`.
Its stop hook rejects inferred mention labels before exit: every `surface_form` must be a
literal word-bounded span in the sealed current-chapter section. The host validator repeats
that check before linking, and the atomic commit remains the final enforcement boundary.
After deploying, follow the backend-neutral
[release rollout](release-runbook.md#first-codex-v2-production-rollout), apply the additive
startup DDL before enabling workers, and update both
`AGY_PLUGIN_VERSION` and `AGY_PLUGIN_SHA256` to the values shipped by the release. Drain
workers before changing the pin; v1 extraction artifacts cannot resume under v2.

A Build treats v1 checkpoints as incomplete and migrates chronologically while retaining
narrative chunks/embeddings. The initial v1→v2 range must start at the first narrative
chapter; later incremental ranges are allowed only after their preceding v2 summaries and
checkpoints exist. If legacy extraction touched front/back matter, chunk cleanup deliberately
requires the clean reset path. For a clean whole-book regeneration, cancel/drain active jobs,
run `reset-codex NOVEL_ID --force`, then Build from the first narrative chapter. Multiple
ranges for one novel are intentionally serialized by both the active-job key and a database
commit lock.

Before enabling `AGY_CODEX_ENABLED`, canary schema 2.0 output on early, late,
checkpoint-end, and (when present) final-volume chapters. Confirm context-token/entity
counts, exact reducer targets, source/context hashes, and provenance validation.

## Pinned CLI option audit

The 1.1.2 `agy --help` surface was reviewed as part of qualification. NovelWiki deliberately
uses `--new-project --print --model --mode=accept-edits --sandbox --print-timeout --log-file`
and the hidden state-root override required for per-run isolation.

| Option | Decision |
|---|---|
| `--add-dir` | forbidden: it widens the single-workspace read/write boundary |
| `--agent` | not used: the qualified installation reports no selectable custom agents, and the bounded initial prompt is deterministic |
| `--continue`, `--conversation`, `--project` | forbidden for workloads: conversation/project reuse can carry story context and mutable state across jobs |
| `--dangerously-skip-permissions` | always forbidden; the runner test asserts it never appears |
| `--prompt`, `--print`, `-p` | `--prompt` is an alias for `--print`; the worker uses the canonical non-interactive `--print` spelling |
| `--prompt-interactive`, `-i` | interactive entry point; unsuitable for a closed-stdin host worker |
| `--new-project` | required so each isolated state has one disposable project |
| `--sandbox` | always enabled in addition to the tool gate |
| `--mode`, `--model`, `--print-timeout`, `--log-file` | explicitly pinned per invocation |

`agy models` and `agy plugin validate/list` are preflight checks. `agent`/`agents`, `models`,
and `changelog` expose only `-h`/`--help`; `install` additionally exposes `--dir`,
`--skip-aliases`, and `--skip-path`; `update` exposes no flags. Plugin management supports
`list`, `import`, `install`, `uninstall`, `enable`, `disable`, `validate`, and `link`, but its
leaf commands do not parse `--help` consistently and can treat it as an operand. The worker
therefore invokes only the read-only `plugin list` and `plugin validate` forms with validated
arguments. Registry mutation, `install`, and `update` are never worker actions: drain the
worker, test the candidate binary separately, then update the version/hash pin manually. The
official web reference still contains some legacy `/fast` text, while the pinned CLI changelog
and modes page say `/fast`/`/planning` were removed in 1.1.0; the installed binary help and
qualified `--mode` values are the runtime source of truth.

## Incidents

Start with the structured journal stream:

```bash
journalctl --user -u novelwiki-agy-worker.service -f -o cat
```

Every claimed job identifies its actual `job_kind` and `agy_workload`, with `job_id`,
`ai_run_id`, model, attempt, preflight state, subprocess PID/exit code, stdout/stderr byte
counts, model-request/tool-confirmation/sandbox/hook/planner counters, duration,
retry/provider-wait decision, and traceback on exceptions. AGY print mode does not expose
provider token counts, so `agy_token_usage_available=false`; request counters are the bounded
proxy. See
[operations/logging.md](operations/logging.md) for the field/event reference and Loki
queries.

- Immediate new-work kill switch: set `AGY_ENABLED=false` and restart the web/worker settings
  consumers. Queued AGY jobs remain explicit; they do not silently spend API quota.
- Codex-only kill switch: set `AGY_CODEX_ENABLED=false`. Scheduling and worker
  reauthorization both reject `codex_extract`, while an enabled translation grant can remain.
- Quota/provider wait: inspect the official quota UI, avoid tight retry, then use the admin
  “Retry waiting jobs” action after capacity returns.
- Authentication: stop claiming, repeat the official login flow under the service user, run the
  explicit consuming smoke test, then resume.
- CLI/plugin update: drain/disable, record old hashes, update manually with
  `AGY_CLI_DISABLE_AUTO_UPDATE=true` during tests, re-run validator/fake/authenticated
  canary/golden samples, then change pins. Never let a diagnostic run silently establish a
  new production pin.
- Stuck run: request job cancellation. The runner sends TERM then KILL to the verified process
  group. On restart the worker reaps verified orphan process groups before claiming.

Workspaces live under `AGY_WORK_DIR`, mode 0700, outside the checkout/public assets. Successful
and failed artifacts are retained only for the configured windows; normal APIs never expose raw
logs, paths, prompts, account details, or story-bearing diagnostics.
