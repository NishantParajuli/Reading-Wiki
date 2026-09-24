# Security model

> The controls, layer by layer, with pointers to the code that implements them and the
> eval suite that regression-tests them. The product-level spoiler boundary is treated
> as a security property too — see
> [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

## Authentication & sessions (Identity)

- Argon2id password hashing (`argon2-cffi`); OAuth-only accounts have no hash at all.
- **Server-side opaque sessions**: the `tg_session` cookie (httpOnly, `Secure` per
  `COOKIE_SECURE`) carries a random token; the DB stores only its hash; deletion =
  instant revocation (logout, ban, admin "revoke sessions"). Expiry is fixed at creation
  using `SESSION_TTL_DAYS` (30 by default); reads update `last_seen_at`, not expiry.
  `SESSION_SECRET` signs OAuth state only. Rotating it invalidates in-flight OAuth
  handshakes; sessions and email tokens use unkeyed SHA-256 hashes and remain valid.
  Revoke the relevant session rows when existing logins must be invalidated.
- Email verification and password reset use single-use, expiring, hashed tokens.
- Registration, password changes/resets, and email verification use database transactions
  across their account, token, and session writes. Failures cannot consume a token without
  completing its action or commit a password change without its session revocation.
- **Durable rate limits** (`auth_rate_limits`, fixed windows, scoped hashes — never raw
  IPs/emails at rest): login per-IP/per-account, register per-IP, reset request per-IP/
  per-email, reset submit per-IP/per-token. Survive restarts; shared across workers.
- Suspended/banned status is enforced in the session dependency itself.
- The shared spending policy also rejects inactive accounts, including admins, when a
  background worker checks eligibility or reserves quota without an HTTP session.
- Eval: `auth_security_tests.py`.

## CSRF & browser-facing headers (Platform Web)

- Double-submit CSRF on every mutating `/api` request (constant-time compare of the
  `tg_csrf` cookie vs the `x-tideglass-csrf`/`x-csrf-token` header); pre-auth mutations
  require the custom `x-tideglass-request: 1` header instead. 403 before any handler.
- CSP `default-src 'self'` (no external script/connect/object; `frame-ancestors
  'none'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`.
- CORS: explicit origin list only (credentialed requests forbid `*`).
- Eval: `csrf_tests.py`.

## Authorization

- Router-level `Depends(current_user)` on all `/api` (except `/api/auth`);
  `require_admin` on `/api/admin`. Spending routes and workers use Identity's spending
  policy and the relevant monthly or read-side limits; explicitly verification-gated
  endpoints also use `require_verified`.
- Novel access is centralized in Catalog (`require_readable`/`require_editable` —
  ownership + visibility + admin). Generic/import jobs are ownership-scoped. Narration
  also lets readers with current novel access observe shared base-audio/book jobs;
  another reader's overlay job remains private. A missing/deleted requester does not
  bypass the novel check. Non-admin cancellation remains restricted to the requester.
- Assets: only avatars and the SPA are public static; novel images, import previews,
  and audio stream through permission-checked routes. Experience rewrites historical
  public URLs onto those routes. Eval: `asset_security_tests.py`.

## SSRF & scraping (Acquisition)

`safe_fetch.py`: HTTP(S)-only, DNS results and every redirect hop must resolve to
**public** addresses, response size/time caps, same-host binding by default with
explicit adapter allowlists. Curl connects to the validated DNS addresses using fresh
direct connections while preserving hostname/TLS checks; environment and session proxies
are bypassed to prevent an unchecked proxy-side lookup. Temporary session options are
serialized and restored. Eval: `scraper_security_tests.py`; provider-free transport
regressions: `tests/unit/modules/acquisition/test_scraper_dns_pinning.py`. Details:
[../pipelines/scraping.md](../pipelines/scraping.md).

Raw archive acquisition follows the same checked download boundary, including its explicit
asset host. Archive members are read in memory, with entry-count, expanded-size, member-size,
path, and symlink checks; the scraper does not extract files or stage images. The supplied
ZIP password is stored in `sources.config` JSONB and omitted from reader-facing novel source
metadata. It is not built into the application or included in chapter text/checkpoint URLs.
Supported formats and limits: [supported sites](../pipelines/supported-sites.md).

## Upload hardening (Acquisition)

Single-shot size caps; chunked uploads are bounded at init, append-only/contiguous (no
gaps, no sparse forgery, no disk exhaustion), streamed hashing (never whole-file in
memory), abandoned-session GC. EPUB container/package XML disables network access, external
DTD loading, and entity expansion, and rejects document-defined entities. Rendered import
HTML is sanitized (nh3). Eval:
`upload_security_tests.py`, `import_pdf_tests.py`.

## Cost abuse (denial-of-wallet)

- Monthly quotas cover translated chapters, OCR pages, Codex builds, and generated
  narration chapters. Non-admin spending requires a verified, active account; active
  admins bypass monthly caps but usage is recorded.
- Read-side AI (Ask/profile synthesis/recap) has separate per-user, per-kind hourly
  uncached caps and concurrency slots
  (self-expiring), question-length bounds, and hard clamps on model-planned tool
  arguments so a prompt-injected planner can't fan out retrieval
  (`ASK_TOOL_MAX_*`). Cache hits bypass gates because they cost nothing; admins bypass
  the hourly and concurrency limits. Read-side verification requirements are configurable
  through `ASK_REQUIRE_VERIFIED` and `ENTITY_PROFILE_SYNTH_REQUIRE_VERIFIED`.
- Provider budgets: persistent Gemini daily counter; jobs pause (`ocr_paused`,
  `waiting_provider`) instead of hammering providers.
- Estimates before spend (`/cost-estimate`), explicit reserve/refund accounting with
  exactly-once settlement. Eval: `ai_cost_controls_tests.py`,
  `durable_jobs_tests.py`.

## Sidecar exposure

GPU sidecars sit on a private Docker bridge with **unpublished ports**; expensive
endpoints require the shared `X-Tideglass-Sidecar-Token` and fail closed without it
(`SIDECAR_ALLOW_UNAUTHENTICATED=1` is an explicit dev-only opt-out). Eval:
`sidecar_auth_tests.py`.

## AGY containment (AI Execution)

Defense-in-depth around a subscription CLI that executes model output:
dormant-by-default (global flag **and** per-user, per-workload admin grants; Codex has an
additional default-off global switch; admin role alone grants nothing) · binary + plugin
SHA-256 pins and model-catalog preflight · isolated mutable CLI state and trusted-workspace
settings per run · sealed read-only inputs, size-capped workspaces outside the
checkout/public roots · positive-allowlist child environment, own process group,
timeout→grace→kill, identity-verified orphan reaping · plugin hooks denying
command/web/MCP/subagent/directory-search/outside-workspace access · runtime proof that
exactly the pinned two hooks loaded from one file · model-request and no-output-progress
loop ceilings · all artifacts size-capped, hash-verified, traversal-safe, schema-validated ·
re-authorization immediately before execution · run records with input/output hashes. App
configuration contains only the CLI credential directory path; NovelWiki never loads the
OAuth token into settings or the child environment.
Eval: `agy_contract_tests.py`, `agy_policy_tests.py`, `agy_runner_tests.py`,
`agy_workload_tests.py`. Ops: [../agy-operator-runbook.md](../agy-operator-runbook.md).

## OpenAI Codex containment (AI Execution)

The App Server backend has an independent dormant-by-default global switch, extraction
switch, and per-user/workload grant. Preflight checks the official executable version
and optional SHA-256 pin, verifies a worker-owned `auth.json` with mode `0600`, confirms
a ChatGPT subscription account, and requires the configured models to appear in
`model/list`. NovelWiki links that credential into a new private per-run `CODEX_HOME`
without parsing it; persisted history, analytics, and web search are disabled.

Each task uses a fresh ephemeral App Server thread over bounded stdio JSONL with
`approvalPolicy=never`, a read-only sandbox, network access disabled, and no
MCP/apps/plugins/skills/subagents or external files. The model returns a strict
Structured Outputs object; the host normalizes it, injects trusted source identity,
materializes artifacts, and runs the same hash/schema/provenance validators and atomic
commit path as AGY. Workspaces and streams are capped, cancellation terminates the owned
process group, safe error summaries exclude raw provider messages, authorization is
rechecked immediately before execution, and run records preserve contract/input/output
hashes. Eval: `tests/unit/ai_execution/test_openai_codex_app_server.py`,
`tests/unit/ai_execution/test_openai_codex_smoke.py`,
`tests/unit/platform/test_openai_codex_model_policy.py`. Ops:
[../openai-codex-operator-runbook.md](../openai-codex-operator-runbook.md).

## The spoiler boundary (product security)

Server-computed ceilings from observed reads; `WHERE chapter <= ceiling` at the
SQL/retrieval layer; ceiling-keyed caches; tools that return nothing beyond the bound;
the LLM never sees out-of-bounds text. Client-supplied ceilings can lower, never raise.
Eval: `spoiler_tests.py`, `spoiler_boundary_tests.py`.

## Auditability

`audit_events` (append-only; job lifecycle, quota movements, auth/admin actions) with
`X-Request-ID` correlation from edge to event. Deployment surface: loopback-only web
port behind a Cloudflare tunnel; non-root container user; secrets only via environment.
