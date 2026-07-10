# NovelWiki Antigravity worker

The web/API worker remains universal. AGY runs only in this separate host service under the
OS user that completed the official AGY browser/keyring login.

## Enable

1. Confirm `agy --version` is at least 1.1.1 and `sha256sum ~/.local/bin/agy` matches
   `AGY_BINARY_SHA256`.
2. Confirm the exact configured model names appear in `agy models`.
3. Validate the plugin:
   `agy plugin validate novelwiki/agy/plugin/novelwiki-ai`.
4. Complete official AGY sign-in and run one disposable manual print-mode file-write test.
5. Verify sandbox/permission rules deny command, web, MCP, subagent, and outside-workspace access.
6. Set `AGY_ENABLED=true`, install `deploy/novelwiki-agy-worker.service` under
   `~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now novelwiki-agy-worker`.
7. Use the admin Antigravity health panel, then explicitly grant one owner only
   `translate_batch`. Do not infer access from admin role.

Use `loginctl enable-linger <user>` if the user service must survive logout. The service must
retain access to the authenticated user's DBus/keyring session.

## Incidents

- Immediate new-work kill switch: set `AGY_ENABLED=false` and restart the web/worker settings
  consumers. Queued AGY jobs remain explicit; they do not silently spend API quota.
- Quota/provider wait: inspect the official quota UI, avoid tight retry, then use the admin
  “Retry waiting jobs” action after capacity returns.
- Authentication: stop claiming, repeat the official login flow under the service user, run the
  explicit consuming smoke test, then resume.
- CLI/plugin update: drain/disable, record old hashes, update manually, re-run validator/fake
  tests/golden samples, then change pins.
- Stuck run: request job cancellation. The runner sends TERM then KILL to the verified process
  group. On restart the worker reaps verified orphan process groups before claiming.

Workspaces live under `AGY_WORK_DIR`, mode 0700, outside the checkout/public assets. Successful
and failed artifacts are retained only for the configured windows; normal APIs never expose raw
logs, paths, prompts, account details, or story-bearing diagnostics.
