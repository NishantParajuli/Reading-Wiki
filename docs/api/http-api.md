# HTTP API reference

> **Source of truth:** the contract snapshot `tests/contracts/snapshots/routes.json`
> (119 routes) and `openapi.json` (schemas). A live instance serves interactive docs at
> `/docs` (Swagger) and `/redoc`, and the raw spec at `/openapi.json`. This page is the
> annotated map: every route family, grouped by owning module, plus the cross-cutting
> rules. For the literal 119-row method/path/endpoint-name list, use
> [http-route-inventory.md](http-route-inventory.md).

## Cross-cutting rules

**Authentication.** Cookie sessions only. `POST /api/auth/login` (or register/OAuth)
sets the httpOnly `tg_session` cookie; every `/api` route outside `/api/auth` requires it
(router-level `Depends(current_user)`), and `/api/admin/*` requires an admin session.
401 = not signed in; 403 = signed in but not allowed (or unverified email on spend
surfaces). Suspended/banned accounts are rejected at the dependency.

**CSRF.** Mutating `/api` requests must send header `x-tideglass-csrf` (or
`x-csrf-token`) matching the `tg_csrf` cookie (double-submit; compared constant-time).
The five pre-auth mutations (`register`, `login`, `request-reset`, `reset`, `verify`)
instead require the custom header `x-tideglass-request: 1`. Violations: 403 before any
handler runs.

**Request IDs.** Send `X-Request-ID` to correlate; the server echoes it (or mints one)
and stamps it on audit events.

**Error shape.** `{"detail": "..."}` with conventional codes: 400 invalid operation,
401/403 auth, 404 not found, 409 conflict/already-active-job, 402/429 quota and rate
limits (429 carries `Retry-After` where applicable), 422 validation.

**Spoiler bounding.** Every codex read takes an optional `ceiling` query/body parameter,
but the server clamps it to the caller's **trusted** ceiling (server-observed
`max_chapter_read`; owners/admins may see the full span). Sending a bigger number does
not unlock anything.

---

## Identity — auth (`/api/auth`, mixed public/session-gated routes)

The router has no blanket session dependency because registration/login/reset/OAuth must
be reachable before authentication. Individual account routes (`logout`, `me`,
`change-password`, and linked-provider reads) require a valid session; public mutations
apply their own durable rate limits.

| Method & path | Purpose |
|---|---|
| `POST /api/auth/register` | create account (username/email/password); sends verification mail (or logs the link without SMTP) |
| `POST /api/auth/login` | password login → session cookie. Per-IP and per-account windows |
| `POST /api/auth/logout` | delete the session row |
| `GET  /api/auth/me` | current user: profile, prefs, quota limits, capabilities (e.g. AGY availability) |
| `POST /api/auth/change-password` | set/change password (current one required if set) |
| `GET  /api/auth/verify` · `POST /api/auth/verify` | email verification (link target · SPA confirm) |
| `POST /api/auth/request-reset` · `POST /api/auth/reset` | password reset flow (single-use hashed tokens) |
| `GET  /api/auth/providers` | which OAuth buttons to show |
| `GET  /api/auth/oauth/{provider}/start` · `…/callback` | Google/Discord code flow (signed `state`) |
| `GET  /api/auth/links` | providers linked to the signed-in account |

## Identity — account (`/api`, auth)

`GET /api/me/usage` (monthly spend vs caps) · `PATCH /api/me` (profile + synced reader
prefs) · `POST /api/me/avatar`.

## Catalog (`/api`, auth)

`POST /api/novels` (create, private by default, optional first source) ·
`PATCH /api/novels/{id}` (metadata owner/admin; shelf per-user) ·
`DELETE /api/novels/{id}` · `POST /api/novels/{id}/cover` ·
`PATCH /api/novels/{id}/visibility` (global = admin-only) ·
`POST|DELETE /api/novels/{id}/library` (add/remove from my library) ·
`POST /api/novels/{id}/tag-suggestions` · `GET …/tag-suggestions` ·
`POST …/tag-suggestions/{sid}/accept|reject`.

## Experience — composite reads (`/api`, auth)

`GET /api/home` (continue reading/listening, active jobs, recent imports, newest shared) ·
`GET /api/activity` (all three job systems in one feed; `status=active` filter) ·
`GET /api/novels` (my library grid) · `GET /api/novels/{id}` (novel detail composite) ·
`GET /api/discover` (shared library; filters: `q`, `language`, `tag`, `translation`,
`has_codex`, `has_audio`, `freshness`, `sort`, paging) ·
`GET /api/users/{username}` (public profile) ·
`GET /api/novels/{id}/health` (owner pipeline health) ·
`GET /api/novels/{id}/cost-estimate` (`action=codex_build|translate|audiobook`, range
params — estimated units vs remaining quota, shown before spending) ·
`POST /api/novels/{id}/recap` (spoiler-safe story-so-far; executed by Codex, cached per
(novel, ceiling)). The SPA requests `Accept: application/x-ndjson`; the response emits an
immediate `started` event, periodic `heartbeat` events, then one `result` or `error` event so
a cache-miss recap can run beyond the reverse proxy's 120-second read timeout. Clients that
do not request the stream continue to receive the original JSON response.

## Reading (`/api`, auth)

TOC/content: `GET /api/novels/{id}/chapters` · `GET /api/novels/{id}/chapter/{number}`
(content + prev/next; opening a pending raw chapter translates it inline and prefetches
the next few) · `PUT …/chapter/{number}/content` (owner/admin base edit; bumps
`content_version`).
Progress: `GET|PUT /api/novels/{id}/progress` (`last_chapter`, `scroll_pct`;
`max_chapter_read` only ever rises).
Bookmarks: `GET|POST /api/novels/{id}/bookmarks` · `DELETE …/bookmarks/{bid}`.
Overlays & contribute-back: `PUT|DELETE …/chapter/{n}/overlay` ·
`POST …/chapter/{n}/self-translate` (metered to caller) ·
`POST …/chapter/{n}/resolve` (base-vs-mine conflict) ·
`POST …/chapter/{n}/contribute` · `GET /api/novels/{id}/contributions` ·
`POST …/contributions/{cid}/accept|reject`.

## Acquisition (`/api`, auth)

Sources & scraping: `GET /api/adapters` · `POST /api/novels/{id}/sources` ·
`PATCH …/sources/{sid}` (offset change runs the renumbering workflow; refused while
codex artifacts exist) · `POST /api/novels/{id}/scrape` (durable job; `409` dedupe onto
the active one).
Upload: `POST /api/import/upload` (≤ `MAX_UPLOAD_MB`) · chunked:
`POST /api/import/upload/init` → `PUT /api/import/upload/{job}/chunk` (contiguous,
capped) → `POST …/complete` (streamed hash verify) · `GET …/status` ·
`POST /api/import/scan-incoming` · `POST /api/import/batch` ·
`POST /api/import/commit-series`.
Jobs: `GET /api/import/jobs` · `GET|DELETE /api/import/jobs/{id}` ·
`PUT …/plan` (edit segmentation before commit) · `POST …/confirm-ocr` (paid-OCR consent
gate) · `POST …/commit` · `POST …/cancel`.
Assets (access-controlled streaming): `GET /api/assets/novels/{novel_id}/{filename}` ·
`GET /api/assets/import-jobs/{job_id}/{filename}`.

## Translation (`/api`, auth)

`POST /api/novels/{id}/translate` (durable batch over a range; backend-resolved,
quota-reserved) · `GET|PUT /api/novels/{id}/glossary` ·
`DELETE …/glossary/{term_id}` · `POST …/glossary/seed` (from codex entities).

## Codex (`/api`, auth; every read ceiling-bounded)

`GET /api/novels/{id}/meta` (chapter span + display info for the ceiling control) ·
`GET /api/novels/{id}/stats` · `GET /api/novels/{id}/entities`
(`ceiling`, `type`, `q`) · `GET /api/novels/{id}/entity/resolve?name=…` ·
`GET /api/novels/{id}/entity/{eid}` (profile; wiki-cache fast path, LLM synthesis on
miss) · `GET …/entity/{eid}/relationships` (`other_id` filter) · `GET …/entity/{eid}/timeline` ·
`GET …/entity/{eid}/identities` (reveals within ceiling) ·
`POST /api/novels/{id}/ask` (agentic Q&A with citations; cache → cost gates → agent) ·
`POST /api/novels/{id}/codex/build` (durable build job; reserves a `codex_builds` unit) ·
`POST /api/novels/{id}/merge-entities` (owner/admin duplicate repair).

## Narration (`/api`, auth)

`GET /api/tts/voices` · `POST /api/novels/{id}/chapter/{n}/audio` (cached ⇒ immediate,
free; else durable job) · `GET …/chapter/{n}/audio/status` ·
`GET …/chapter/{n}/audio.opus` (Range-capable stream) ·
`POST /api/novels/{id}/audiobook` (bounded book batch) · `GET …/audiobook/status` ·
`GET /api/novels/{id}/audio/chapters` (`voice_id`) · `GET …/audio/coverage` ·
`GET /api/tts/jobs/{id}` · `POST /api/tts/jobs/{id}/cancel`.

## Work (`/api`, auth)

`GET /api/jobs` (`kind`, `status`, `novel_id`, `active`, `limit`; non-admins scoped to
self, admins may add `user_id`) · `GET /api/jobs/{id}` · `POST /api/jobs/{id}/cancel`
(queued never starts; running stops before its next expensive stage).

## Admin (`/api/admin`, admin session; served by Experience)

`GET /users` · `PATCH /users/{id}` (status/role/quota overrides; null resets) ·
`DELETE /users/{id}` · `GET /usage` (platform spend) · `GET /novels` ·
`GET /global-novels` · AI backend policy: `GET|PUT|DELETE
/users/{id}/ai-backend-policy` · AGY ops: `GET /ai/agy/health` ·
`POST /ai/agy/retry-waiting` · `POST /ai/agy/smoke-test`.

## Platform

`GET /health` (`{"status":"healthy",…}`) · `GET /docs`, `/docs/oauth2-redirect`,
`/redoc`, `/openapi.json` · everything else falls through to the SPA
(`index.html` for extension-less paths; hashed assets cached immutable).

---

### Changing the API

Any route addition/change must regenerate `routes.json`/`openapi.json`/`responses.json`
via `uv run python scripts/contracts.py --update` — the snapshot diff is part of the review
([../architecture/enforcement.md](../architecture/enforcement.md)). Frontend calls live
in the matching slice's `api.js` (checker-verified module boundaries; inventory frozen in
`frontend_inventory.json`).
