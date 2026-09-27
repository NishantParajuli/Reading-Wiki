# HTTP API reference

> **Source of truth:** the contract snapshot `tests/contracts/snapshots/routes.json`
> (130 routes) and `openapi.json` (schemas). A live instance serves interactive docs at
> `/docs` (Swagger) and `/redoc`, and the raw spec at `/openapi.json`. This page is the
> annotated map: every route family, grouped by owning module, plus the cross-cutting
> rules. For the literal 130-row method/path/endpoint-name list, use
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

**Spoiler bounding.** Codex knowledge reads take an optional `ceiling` query/body parameter,
but the server clamps it to the caller's **trusted** ceiling (server-observed
`max_chapter_read`, including owners/admins; the first stored chapter is the fallback
without progress). Sending a bigger number does
not unlock anything. Illustration gallery and PNG reads use their stored/requested
chapter boundary against the same trusted progress. Owners/admins may queue future
illustrations through the Manage range endpoint without unlocking them or advancing progress.

---

## Identity — auth (`/api/auth`, mixed public/session-gated routes)

The router has no blanket session dependency because registration/login/reset/OAuth must
be reachable before authentication. Individual account routes (`logout`, `me`,
`change-password`, and linked-provider reads) require a valid session; public mutations
apply their own durable rate limits.

| Method & path | Purpose |
|---|---|
| `POST /api/auth/register` | create account (username/email/password); sends verification mail when SMTP is configured. Without SMTP, attempted mail is logged with its token redacted |
| `POST /api/auth/login` | password login → session cookie. Per-IP and per-account windows |
| `POST /api/auth/logout` | delete the session row |
| `GET  /api/auth/me` | current user: profile, prefs, quota limits, capabilities (including AGY/OpenAI Codex availability) |
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
(novel, ceiling)). Long AI-backed Codex reads (`recap`, `ask`, and an uncached entity profile)
support `Accept: application/x-ndjson`; the response emits an immediate `started` event,
periodic `heartbeat` events, then one `result` or `error` event so generation can run beyond
the reverse proxy's 120-second read timeout. Clients that do not request the stream continue
to receive the original JSON response.

## Reading (`/api`, auth)

TOC/content: `GET /api/novels/{id}/chapters` · `GET /api/novels/{id}/chapter/{number}`
(content + prev/next; opening a pending raw chapter translates it inline and prefetches
the next few) · `PUT …/chapter/{number}/content` (owner/admin base edit; bumps
`content_version`).
Progress: `GET|PUT /api/novels/{id}/progress` (`last_chapter`, `scroll_pct`;
`max_chapter_read` advances on served chapter reads, never from this PUT). The resume
chapter must be finite and exist; `scroll_pct` must be finite and within `[0, 1]`.
Invalid numbers/ranges return 422; missing chapters return 404.
Bookmarks: `GET|POST /api/novels/{id}/bookmarks` · `DELETE …/bookmarks/{bid}`. Creation
requires a finite chapter number (422 otherwise) that exists in this novel (404 otherwise).
Overlays & contribute-back: `PUT|DELETE …/chapter/{n}/overlay` ·
`POST …/chapter/{n}/self-translate` (metered to caller) ·
`POST …/chapter/{n}/resolve` (base-vs-mine conflict) ·
`POST …/chapter/{n}/contribute` · `GET /api/novels/{id}/contributions` ·
`POST …/contributions/{cid}/accept|reject`.

## Acquisition (`/api`, auth)

Sources & scraping: `GET /api/adapters` · `POST /api/novels/{id}/sources` ·
`PATCH …/sources/{sid}` (offset change runs the renumbering workflow; refused while
codex artifacts exist) · `POST /api/novels/{id}/scrape` (durable job; repeated requests
with the same target/options return `200` with the active `job_id` and `deduped=true`).
The adapter registry exposes `name`, `label`, `requires`, `default_language`, and
`start_url_hint`; [supported sites](../pipelines/supported-sites.md) lists accepted URLs
and per-site limits. Source creation supports a `config` object; Raw FuckNovelpia uses
`config.archive_password` for encrypted ZIPs. Source PATCH merges supplied `config` keys
into the existing object, preserving unrelated settings; use it to replace an archive
password. Source config is stored but omitted from
the novel-detail source projection. The HTTP source defaults are `language="en"` and
`is_raw=false`, so API clients must explicitly select raw-language behavior.
Chapter offsets must be finite numbers, and an HTTP scrape limit must be at least 1.
Source config must contain valid JSON values: non-finite numbers, null characters, and
invalid Unicode are rejected with `422`. `archive_password`, when supplied, must be a
string; an empty string clears it. Source text fields also reject null characters and
invalid Unicode, while their existing nullable fields remain nullable. Updates validate
all supplied fields before renumbering chapters. Creating a novel with an invalid nested
source returns `422` and leaves no novel, source, or library entry behind.

Account cookies: `GET|PUT|DELETE /api/settings/novelpia-cookies` operate only on the
signed-in user's Novelpia connection. PUT accepts exactly `{"cookies": [...]}`, where
the array is an EditThisCookie-style export (1–100 entries). The request is capped at
64 KiB (`413`); malformed JSON or invalid login-cookie data returns `422` without
echoing credential values. Only `TKEY`, `LOGINKEY`, and `USERKEY` are retained, `TKEY`
is required, and accepted login-cookie domains are `novelpia.com`, `.novelpia.com`, or
`global.novelpia.com` with root path `/`. Other cookie names are discarded. PUT replaces
the saved set; DELETE removes it. Mutation requests require the usual CSRF protection.
All successful responses contain only `configured`, `usable`, `updated_at`, and
`cookies: [{name, domain, expires_at}]` and use `Cache-Control: no-store`. `usable`
means a TKEY exists with no known past storage expiry, not that Novelpia has verified
the login or granted chapter access. No endpoint returns stored cookie values.

The `global-novelpia` scrape adapter uses the requesting job user's saved cookies,
including when an admin scrapes another owner's novel. Sources and jobs do not store
cookie values. With the optional browser service enabled, an ad gate gets one normal
browser completion attempt per episode followed by an independent API access retry.
Unresolved login/ad/unlock requirements fail with a recovery instruction while retaining
chapters already saved; completing the requirement on Novelpia and
retrying resumes ingestion. See [Novelpia setup](../pipelines/supported-sites.md#novelpia-global-account-access).

Upload: `POST /api/import/upload` (≤ `MAX_UPLOAD_MB`) · chunked:
`POST /api/import/upload/init` → `PUT /api/import/upload/{job}/chunk` (contiguous,
capped) → `POST …/complete` (streamed hash verify) · `GET …/status` ·
`POST /api/import/scan-incoming` · `POST /api/import/batch` ·
`POST /api/import/commit-series` (`job_ids`; optional editable `novel_id` appends the
ordered volumes instead of creating a novel).
Jobs: `GET /api/import/jobs` · `GET|DELETE /api/import/jobs/{id}` ·
`PUT …/plan` (`plan` plus optional `metadata`: `title`, `author`, `description`,
`language`, `series`, numeric `series_index`, and `volume_label`; supplied metadata
overrides parser/filename values at commit) · `POST …/confirm-ocr` (paid-OCR consent
gate) · `POST …/commit` (`mode=new|append|replace`; for `new`/`append`,
`as_volume=true` groups under the saved or detected volume label and computes numbering
automatically, serializing concurrent automatic appends per target novel; `replace`
preserves the source's labels/offset numbering and rejects `as_volume=true` with 422) ·
`POST …/cancel`.
Assets (access-controlled streaming): `GET /api/assets/novels/{novel_id}/{filename}` ·
`GET /api/assets/import-jobs/{job_id}/{filename}`.

## Translation (`/api`, auth)

`POST /api/novels/{id}/translate` (durable batch over a range; backend-resolved,
quota-reserved) · `GET|PUT /api/novels/{id}/glossary` ·
`DELETE …/glossary/{term_id}` · `POST …/glossary/seed` (from codex entities).

## Codex (`/api`, auth; every read ceiling-bounded)

`GET /api/novels/{id}/meta` (chapter span + display info for the ceiling control) ·
`GET /api/novels/{id}/stats` (ceiling-bounded knowledge counts plus operational
`built_through_chapter` and `built_chapter_count`; build metadata
may extend beyond the reader's ceiling but contains no story content) · `GET /api/novels/{id}/entities`
(`ceiling`, `type`, `q`) · `GET /api/novels/{id}/entity/resolve?name=…` ·
`GET /api/novels/{id}/entity/{eid}` (profile; wiki-cache fast path, LLM synthesis on
miss followed by fail-closed grounding verification/repair; optional heartbeat NDJSON) ·
`GET …/entity/{eid}/relationships` (`other_id` filter) · `GET …/entity/{eid}/timeline` ·
`GET …/entity/{eid}/identities` (reveals within ceiling) ·
`POST /api/novels/{id}/ask` (agentic Q&A with retrieved-evidence-only citations;
cache → cost gates → agent → semantic verifier/repair → hard machine provenance checks;
hard failures return a safe, uncached insufficient-evidence answer, while citation placement
alone does not discard an otherwise grounded answer; optional heartbeat NDJSON) ·
`POST /api/novels/{id}/codex/build` (durable build job; reserves a `codex_builds` unit) ·
`POST /api/novels/{id}/merge-entities` (owner/admin duplicate repair).

Chapter art uses `GET|POST /api/novels/{id}/chapters/{chapter}/illustrations`,
`GET|POST /api/novels/{id}/illustrations`, and
`GET /api/novels/{id}/illustrations/{art_id}/image`. The chapter list returns `items`,
`can_generate`, `unavailable_reason`, and the requester's latest matching job as `active_job`
(including failed/canceled states; `null` if absent or completed). Items contain kind,
title, caption, style, source chapter, prompt/design notes, evidence, optional placement
(`position: "start"|"after"|"end"`, exact `anchor`, character `offset`), and authenticated
image URL. The image route returns `image/png` with `Cache-Control: private, no-store`;
all art reads verify novel/chapter access and source freshness.

Single-chapter generation accepts
`{count: null, style: "luminous"|"celestial"|"ink", force: false}`. Omitted or `null`
count lets AI choose one to three images; integers 1–3 remain accepted for legacy clients.
The default style is Luminous. Generation requires editable chapter access and the granted,
available OpenAI Codex backend. It returns `job_id`, with `created` for newly scheduled
or deduplicated work, or `already_created: true` when current art is reused.

Manage's `GET /api/novels/{id}/illustrations` requires owner/admin edit access and returns
`can_generate`, `unavailable_reason`, and the latest range job in `active_job`, including
`done` so Manage can show completion. This differs from the chapter gallery, which clears
completed jobs to `null`. The response reveals no chapter text or art. `POST` accepts `{from_chapter: 25, to_chapter: 100, style: "luminous", force: false}`.
Bounds are inclusive, finite nonnegative chapter numbers; the upper bound must not precede
the lower. It returns `job_id`, `created`, and `chapter_count`, scheduling one durable job
over at most 1,000 existing translated story chapters/interludes, including fractional
chapter numbers. Missing/untranslated and
non-story chapters are skipped; valid complete art in the chosen style is skipped unless
`force` is true. Owners/admins may schedule ahead of reading, but image access remains
bounded by trusted reading progress. Each included chapter is limited to 150,000 text
characters. No eligible text returns 404; invalid ranges/counts return 422.

Denied access returns 403, changed source returns 409, unavailable provider returns 503,
and active-job limit exhaustion returns 429. There is no API fallback or monthly
Codex-build reservation. [Illustration pipeline](../pipelines/chapter-illustrations.md).

## Narration (`/api`, auth)

`GET /api/tts/voices` · `POST /api/novels/{id}/chapter/{n}/audio` (cached ⇒ immediate,
free; else durable job) · `GET …/chapter/{n}/audio/status` ·
`GET …/chapter/{n}/audio.opus` (Range-capable stream) ·
`POST /api/novels/{id}/audiobook` (bounded book batch) · `GET …/audiobook/status` ·
`GET /api/novels/{id}/audio/chapters` (`voice_id`) · `GET …/audio/coverage` ·
`GET /api/tts/jobs/{id}` · `POST /api/tts/jobs/{id}/cancel`.

For cached audio, `audio/status` includes `timing`. Newly generated audio returns a
versioned manifest with actual `start_ms`, `speech_end_ms`, and `end_ms` boundaries per
generated paragraph plus its visible `source_index`. Legacy audio returns `timing: null`;
clients must keep playback available and disable synchronized highlighting. During forced
regeneration, the previous cache remains playable and the same response also includes the
active `job_id` and `job_status`; clients must follow that job rather than treating the
cached row as the completed regeneration.

New audio generation returns 503 when `TTS_ENABLED=false`, and 429 for exhausted
narration quota; existing cache hits and active jobs are returned before those generation
checks. Cached audio remains playable when generation is disabled. An audio cache row
whose file is missing returns 410. Non-admin job reads require current access to the
novel and either ownership of the job or a shared base-audio/book target; orphaned jobs
do not bypass this check. Only the requester or an admin can cancel a job, and late
worker completion cannot overwrite its canceled status.

## Work (`/api`, auth)

`GET /api/jobs` (`kind`, `status`, `novel_id`, `active`, `limit`; non-admins scoped to
self, admins may add `user_id`) · `GET /api/jobs/{id}` · `POST /api/jobs/{id}/cancel`
(queued never starts; running stops before its next expensive stage).

For `codex_build`, extraction progress reports `{step,steps,stage,done,total,current_chapter}`.
`done/total` is the durable whole-job position including chapters committed before a retry;
`current_chapter` is the actual source chapter being processed, and `stage` includes both that
source chapter and its overall position. These fields do not reset to a retry-local `1/N` view.

## Admin (`/api/admin`, admin session; served by Experience)

`GET /users` · `PATCH /users/{id}` (status/role/quota overrides; null resets) ·
`DELETE /users/{id}` · `GET /usage` (platform spend) · `GET /novels` ·
`GET /global-novels` · AI backend policy: `GET|PUT|DELETE
/users/{id}/ai-backend-policy` · AGY ops: `GET /ai/agy/health` ·
`POST /ai/agy/retry-waiting` · `POST /ai/agy/smoke-test`. OpenAI Codex has the same
three operations at `/ai/openai-codex/{health|retry-waiting|smoke-test}`. Translation and
Codex-build request bodies accept `ai_backend=auto|api|agy|openai_codex`.

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
