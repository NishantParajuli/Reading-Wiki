# Experience module (`novelwiki/modules/experience/`)

**Responsibility:** the *composite read* layer — every screen that needs data from
several owners at once: the Continue home, the unified activity feed, the library grid,
novel detail, Discover, public profiles, the novel health panel, cost estimates, and the
entire admin dashboard. Experience is the **only** business module allowed to run
registered, read-only cross-owner SQL projections — and it owns **no tables and writes
none** (checker-enforced: "Experience keeps its SQL projections read-only").

Where an admin screen needs a *mutation* (update a user, grant an AGY policy, retry
waiting jobs), Experience does not write — it calls capabilities injected through its own
application ports, and the owning module performs the write.

---

## Public contract (`public.py`)

Six lines: `ExperienceQueries` with `home(user_id)` and
`activity(user_id, *, active_only, limit)`. Experience is a consumer of everyone and a
dependency of almost no one.

## Read projections

### `adapters/outbound/projections.py::PostgresExperienceProjectionRepository`

"The reviewed read-only cross-module projection registry" — the product reads:

- `library_cards(principal)` — the caller's library grid (novels they own or added),
  joining novels + library entries + progress + chapter spans + provenance flags.
- `novel_detail(novel_id, principal)` — the novel page composite (metadata, sources,
  counts, translation/codex/audio state, permissions).
- `discover(principal, q, language, tag, translation, has_codex, has_audio, freshness,
  sort, offset, limit)` — the shared library (Global + Public the caller hasn't added),
  with filters and provenance badges.
- `public_profile(username, principal)` — identity + reading stats + currently-reading +
  recently-finished + published novels.

### `adapters/outbound/operational_projections.py::PostgresOperationalProjectionRepository`

The operational/admin reads: per-system activity slices (`generic_activity`,
`import_activity`, `tts_activity` — active filters applied in SQL before LIMIT),
`home_rows`, `novel_health`, `translation_units` and `audiobook_missing` (cost-estimate
inputs), `admin_users` (accounts + month usage + effective limits), `admin_usage`
(month totals, active spenders, six-month history, top spenders), `admin_novels`,
`global_novels` (curated Global library + pipeline status), `agy_health`,
`recent_smoke`, `job_run_metadata` (AI-run decoration for job lists).

## HTTP surfaces

### Product (`adapters/inbound/http.py` + `projections_http.py`, `/api`, auth required)

| Route | What it composes |
|---|---|
| `GET /api/home` | continue reading (progress × readable novels), continue listening (narrated novels), active jobs, recent imports, newest shared novels — only novels the caller can actually still read |
| `GET /api/activity` | the caller's jobs across **all three** durable systems (generic + import + TTS), normalized (`_generic_job_row`/`_import_job_row`/`_tts_job_row`), newest-first, with the right cancel endpoint per kind; admins see all users |
| `GET /api/novels` / `GET /api/novels/{id}` | library grid / novel detail |
| `GET /api/discover` | shared-library browsing with filters |
| `GET /api/users/{username}` | public profile |
| `GET /api/novels/{id}/health` | owner-facing pipeline health: codex missing/stale, untranslated raws, missing narration per voice, source freshness, recent pipeline errors |
| `GET /api/novels/{id}/cost-estimate` | units an action (codex build / batch translation / whole-book narration) would consume vs. the caller's remaining monthly quota — shown before any spend |
| `POST /api/novels/{id}/recap` | mounted here, but execution is **Codex-owned** (`CodexRecapApi` injected) — same trusted ceiling and cache as Ask |

Cover/asset URLs in projections are rewritten onto the access-controlled asset routes
(`_rewrite`), so historical public URLs can't bypass permission checks.

### Admin (`adapters/inbound/admin_http.py`, `/api/admin`, `require_admin`)

`GET /users` (search + usage), `PATCH /users/{id}` (status/role/quota overrides — null
resets to default), `DELETE /users/{id}` (cascade personal data; owned novels survive
ownerless), `GET /usage`, `GET /novels`, `GET /global-novels`, and the AI-policy/AGY
panel (`GET/PUT/DELETE /users/{id}/ai-backend-policy`, `GET /ai/agy/health`,
`POST /ai/agy/retry-waiting`, `POST /ai/agy/smoke-test`).

## Application layer

- `application/projections.py` — the projection service in front of the repositories.
- `application/admin_commands.py::ExperienceAdminCommands` — the cross-owner admin
  orchestration behind consumer-owned ports: `AiAdminPort` (policy CRUD + worker
  availability — implemented by AI Execution), `WorkAdminPort` (retry-waiting + smoke-job
  creation — implemented by Work), `AdminAuditPort` (audit trail). Identity's admin
  mutations arrive via the separately injected Identity admin service. This is the
  pattern from the migration completion note: *"Identity, AI Execution, and Work admin
  mutations are injected through Experience-owned application ports."*

## Rules for adding a projection

1. Read-only SQL only — any write belongs to the owner module (add a capability there).
2. Register it in one of the two projection repositories (that *is* the registry the
   checker recognizes; ad-hoc cross-owner SQL elsewhere fails the build).
3. Scope by principal in SQL (ownership/visibility joins), not in Python after the fact.
4. Prefer composing existing owner capabilities when the read is single-owner — a
   projection is only justified when the join genuinely crosses owners.
