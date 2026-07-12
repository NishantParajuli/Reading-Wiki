# Identity module (`novelwiki/modules/identity/`)

**Responsibility:** everything about *who is using the system and what they're allowed to
spend*: accounts, passwords, sessions, OAuth links, email verification/reset, durable
auth rate-limiting, per-user monthly quotas, public profiles/avatars, and admin user
management primitives.

**Owned tables:** `users`, `oauth_accounts`, `sessions`, `email_tokens`,
`auth_rate_limits`, `quota_usage`.

---

## Public contract (`public.py`)

- **`Principal`** — the frozen identity object passed to every other module's permission
  check: `user_id`, `role` (`user`/`admin`, with `.is_admin`), `status`
  (`active`/`suspended`/`banned`), `email_verified`, and `quota_limits` (a mapping of
  quota kind → effective monthly cap, with per-user `users.quota_*` overrides falling
  back to `DEFAULT_QUOTA_*`). Built via `Principal.from_user(user_row, quota_defaults)`;
  the canonical factory other modules receive is `identity/adapters/principals.py::principal_from_user`.
- **`SystemPrincipal(actor="system")`** — non-human actor for CLI/system operations
  (e.g. `add-novel` creates ownerless system novels — intentional per ADR 002).
- **`QuotaApi`** — `check_available(principal, kind, units)`, `reserve(...) -> bool`,
  `refund(user_id, kind, units)`. Quota kinds: `translated_chapters`, `ocr_pages`,
  `codex_builds`, `tts_chapters`.
- **`IdentityQuotaTransactionApi`** — the refund capability bound inside the
  `finalize_job_quota` workflow (transactional, clamped so usage never goes negative).
- **`UserDirectoryApi`** — `labels(user_ids) -> {id: UserLabel(username, display_name)}`,
  used by Experience/Work to decorate job lists without touching `users` directly.
- **`IdentityAdminApi` / `IdentityAdminTransactionApi`** — admin mutations (update role/
  status/quotas, revoke sessions, delete user) with the guard queries (`user_role`,
  `other_admin_count` — you cannot demote/delete the last admin).

## Layer highlights

### Application (`application/`)

- `sessions.py::IdentitySessionService` — token hash lookup → user row; sliding
  `last_seen_at`; revocation by deletion.
- `accounts.py::AccountService` — profile updates (username uniqueness, display name,
  bio, synced reader `prefs`), avatar path bookkeeping.
- `quota.py::QuotaService` — month-bucketed (`period = first of month`) counters in
  `quota_usage`; reserve/consume/refund with per-user overrides; exemption for admins.
- `rate_limits.py` — fixed-window counters keyed by *scoped hashes* (never raw
  emails/IPs/tokens) in `auth_rate_limits`, so abuse control survives restarts without
  storing identifiers.
- `admin.py` — role/status transitions + the last-admin invariant.
- `domain/policies.py` — pure rules (status gating, role checks).

### Inbound adapters

- **`http.py`** (mounted at `/api/auth`, public): `register`, `login`, `logout`, `me`,
  `change-password`, `verify` (GET link + POST confirm), `request-reset`, `reset`,
  `providers`, `oauth/{provider}/start`, `oauth/{provider}/callback`, `links`.
  Each mutation consults the durable rate limiter (per-IP and per-account/email/token
  windows from `AUTH_*` settings → 429). Email delivery functions are injected by
  Bootstrap via `configure_email_delivery(...)` (kept as a stable monkeypatch seam for
  the auth eval tests).
- **`account_http.py`** (authenticated, `/api`): `GET /api/me/usage` (monthly spend vs
  caps), `PATCH /api/me`, `POST /api/me/avatar`.
- **`dependencies.py`** — the FastAPI auth dependencies every other router uses (exported
  at the Platform path `novelwiki.platform.auth`): `current_user` (401 without a valid
  session; loads the full user row and rejects suspended/banned), `optional_user`,
  `require_verified` (403 without a verified email — gates spend surfaces),
  `require_admin`.
- **`cookies.py`** — `tg_session` (httpOnly, Secure per `COOKIE_SECURE`, SameSite) and
  the JS-readable `tg_csrf` cookie for the double-submit CSRF scheme.
- **`presentation.py`** — response shaping: `self_user` (includes prefs, quota limits,
  capabilities like AGY availability), `public_user` (profile-safe subset), `avatar_url`.

### Outbound adapters

- `postgres_users/sessions/auth/accounts/admin/quota/directory.py` — the only SQL
  writers for the six owned tables (auth persistence bundles registration/login/token
  flows; sessions/quota/etc. are split per concern).
- `passwords.py` — Argon2id hash/verify (+ `needs_rehash`); OAuth-only accounts have
  `password_hash NULL` and `verify_password` returns False rather than erroring.
- `tokens.py` — opaque random tokens; only **hashes** are stored (`sessions.token_hash`,
  `email_tokens.token_hash`); `sign`/`unsign`/`stamped` HMAC helpers use
  `SESSION_SECRET` (rotating it invalidates all sessions).
- `oauth.py` — hand-rolled Google/Discord authorization-code flow on httpx: `authorize_url`
  (with signed `state`), `exchange_code` → normalized `(provider_account_id, email,
  username hint)`; providers appear in the UI only when client credentials are configured.
- `email.py` — aiosmtplib transactional mail; with no `SMTP_HOST` the link is logged
  instead of sent (dev mode).
- `avatars.py::AvatarFilesystem` — stores under `ASSET_DIR/_users/<id>/` (the one
  deliberately public asset mount).
- `maintenance.py::cleanup_expired_identity_state` — startup sweep of expired sessions,
  email tokens, rate-limit buckets, and AI request locks.
- `rate_limit.py`, `quota_compat.py`, `worker_lookup.py` — durable limiter persistence and
  the compat-shaped quota/user-lookup functions injected into workers.

## Collaboration notes

- Every module's permission checks receive a `Principal` — Identity never exposes raw
  user rows across the boundary (workers get a minimal injected `load_user`).
- Quota flows: routes check/reserve via `QuotaApi`; durable jobs record reservations on
  the job row and settle exactly once through the `finalize_job_quota` workflow
  (Work + Identity in one transaction). See
  [../pipelines/background-jobs-and-quota.md](../pipelines/background-jobs-and-quota.md).
- Admin *endpoints* live in Experience (`/api/admin/...`); Experience calls Identity's
  injected admin service — Identity owns the mutation, Experience owns the dashboard.

## Security properties worth knowing

- Sessions are server-side and opaque: the cookie value is random; the DB stores its
  hash; logout/ban deletes rows ⇒ immediate revocation. TTL `SESSION_TTL_DAYS` (30).
- All auth abuse controls are DB-backed fixed windows (survive restarts, shared across
  workers): login per-IP (10/10 min) and per-account (5/10 min), registration per-IP
  (5/h), reset request per-IP (5/h) and per-email (3/h), reset submit per-IP (10/h) and
  per-token (5/h).
- Verification/reset tokens: single-use (`used_at`), expiring, hashed at rest.
- A verified email is required before anything that spends money
  (`require_verified`, plus `ASK_REQUIRE_VERIFIED` on read-side AI).
