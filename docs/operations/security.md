# Security model

> The controls, layer by layer, with pointers to the code that implements them and the
> eval suite that regression-tests them. The product-level spoiler boundary is treated
> as a security property too — see
> [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

## Authentication & sessions (Identity)

- Argon2id password hashing (`argon2-cffi`); OAuth-only accounts have no hash at all.
- **Server-side opaque sessions**: the `tg_session` cookie (httpOnly, `Secure` per
  `COOKIE_SECURE`) carries a random token; the DB stores only its hash; deletion =
  instant revocation (logout, ban, admin "revoke sessions"). TTL 30 days.
  `SESSION_SECRET` peppers/signs derived tokens — rotate to invalidate everything.
- Email verification and password reset use single-use, expiring, hashed tokens.
- **Durable rate limits** (`auth_rate_limits`, fixed windows, scoped hashes — never raw
  IPs/emails at rest): login per-IP/per-account, register per-IP, reset request per-IP/
  per-email, reset submit per-IP/per-token. Survive restarts; shared across workers.
- Suspended/banned status is enforced in the session dependency itself.
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
  `require_admin` on `/api/admin`; `require_verified` + quota checks on every spend
  surface.
- Novel access is centralized in Catalog (`require_readable`/`require_editable` —
  ownership + visibility + admin); jobs/imports/TTS are ownership-scoped in their
  services (non-admins can only ever see/cancel their own).
- Assets: only avatars and the SPA are public static; novel images, import previews,
  and audio stream through permission-checked routes. Experience rewrites historical
  public URLs onto those routes. Eval: `asset_security_tests.py`.

## SSRF & scraping (Acquisition)

`safe_fetch.py`: HTTP(S)-only, DNS results and every redirect hop must resolve to
**public** addresses, response size/time caps, same-host binding by default with
explicit adapter allowlists. Eval: `scraper_security_tests.py`. Details:
[../pipelines/scraping.md](../pipelines/scraping.md).

## Upload hardening (Acquisition)

Single-shot size caps; chunked uploads are bounded at init, append-only/contiguous (no
gaps, no sparse forgery, no disk exhaustion), streamed hashing (never whole-file in
memory), abandoned-session GC. Rendered import HTML is sanitized (nh3). Eval:
`upload_security_tests.py`, `import_pdf_tests.py`.

## Cost abuse (denial-of-wallet)

- Everything expensive is quota-metered per user per month with admin-adjustable caps,
  and requires a verified email.
- Read-side AI (Ask/profile synthesis): hourly uncached cap, per-user concurrency slots
  (self-expiring), question-length bounds, and hard clamps on model-planned tool
  arguments so a prompt-injected planner can't fan out retrieval
  (`ASK_TOOL_MAX_*`). Cache hits bypass gates because they cost nothing.
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
dormant-by-default (global flag **and** per-user, per-workload admin grants; admin role
alone grants nothing) · binary + plugin SHA-256 pins and model-catalog preflight ·
sealed read-only inputs, size-capped workspaces outside the checkout/public roots ·
positive-allowlist child environment, own process group, timeout→grace→kill,
identity-verified orphan reaping · plugin hooks denying command/web/MCP/subagent/
outside-workspace access · all artifacts size-capped, hash-verified,
traversal-safe, schema-validated · re-authorization immediately before execution ·
run records with input/output hashes. No AGY credential ever enters app config.
Eval: `agy_contract_tests.py`, `agy_policy_tests.py`, `agy_runner_tests.py`,
`agy_workload_tests.py`. Ops: [../agy-operator-runbook.md](../agy-operator-runbook.md).

## The spoiler boundary (product security)

Server-computed ceilings from observed reads; `WHERE chapter <= ceiling` at the
SQL/retrieval layer; ceiling-keyed caches; tools that return nothing beyond the bound;
the LLM never sees out-of-bounds text. Client-supplied ceilings can lower, never raise.
Eval: `spoiler_tests.py`, `spoiler_boundary_tests.py`.

## Auditability

`audit_events` (append-only; job lifecycle, quota movements, auth/admin actions) with
`X-Request-ID` correlation from edge to event. Deployment surface: loopback-only web
port behind a Cloudflare tunnel; non-root container user; secrets only via environment.
