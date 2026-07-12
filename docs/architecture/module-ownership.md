# NovelWiki module ownership

This is the human-readable ownership map. The executable authority is
`novelwiki/platform/architecture/checks.py::TABLE_OWNERS`; the architecture test fails
when production SQL violates it. Keep this page and that registry in the same change.

| Module | Write-owned tables |
|---|---|
| Platform Database / Observability | `app_migrations`, `audit_events` |
| Identity | `users`, `oauth_accounts`, `sessions`, `email_tokens`, `auth_rate_limits`, `quota_usage` |
| Catalog | `novels`, `library_entries`, `tag_suggestions` |
| Reading | `chapters`, `reading_progress`, `bookmarks`, `chapter_overlays`, `contributions` |
| Acquisition | `sources`, `import_jobs`, `assets` |
| Translation | `translation_glossary` |
| Codex | `chunks`, `entities`, `entity_descriptions`, `entity_aliases`, `identity_links`, `entity_facts`, `relationships`, `events`, `extraction_state`, `wiki_cache`, `query_cache` |
| Narration | `tts_jobs`, `chapter_audio` |
| Work | `jobs` |
| AI Execution | `user_ai_backend_policies`, `ai_request_locks`, `provider_budget`, `ai_execution_runs`, `ai_worker_heartbeats` |
| Experience | none; registered read-only projections only |

Cross-module executable dependencies are injected behind consumer-owned ports.
Cross-module write coordination lives in `novelwiki/workflows`; router, CLI, and worker
adapters do not own transactions or SQL.

## Named cross-module workflows

| Workflow | Participating owners |
|---|---|
| `create_novel_with_source` | Catalog, Acquisition |
| `delete_novel` | Catalog, Acquisition |
| `update_source_offset` | Acquisition, Reading, Codex |
| `commit_import` | Acquisition, Catalog, Reading, Codex |
| `commit_translation` | Reading, Translation, Work |
| `commit_codex_extraction` | Reading, Codex |
| `finalize_job_quota` | Work, Identity |
| `schedule_ai_job` | requesting feature, Identity quota, Work |

The first seven workflows are transaction-bound: every participant is bound to the unit
of work's one connection. `schedule_ai_job` is the explicit exception: it preserves
`reserve → optional owner command → create/dedupe → compensate` ordering and has the
documented process-crash window in ADR 003. Every workflow is SQL-free and contains no
FastAPI, asyncpg, provider, or filesystem implementation.

## Approved cross-owner projections

Experience owns the reviewed, read-only composite projections: Library cards, novel detail,
Discover, public profile, Home, Activity, novel health, cost estimate, job+AI-run view, and the
admin user/usage/novel/AGY views. The exact table set for each projection is the executable
`PROJECTION_TABLES` registry. Authorization commands never consume these projections.

## Where new code goes

- A business rule belongs in the owning module's `domain` or `application` package.
- HTTP, Typer, and worker translation belongs in `adapters/inbound`; inbound adapters cannot use
  database pools or SQL.
- PostgreSQL, filesystem, model provider, sidecar, and queue mechanics belong in
  `adapters/outbound` behind a consumer-owned application port.
- A caller in another module imports the owner's `public.py`, never its adapter or application
  implementation. Executable dependencies are supplied by `bootstrap`.
- An atomic operation that writes more than one owner's tables is a named workflow using a unit of
  work and transaction-bound public APIs.
- A cross-owner display query belongs in Experience and must be added to the projection registry.
- Frontend endpoints and query keys live in `frontend/src/modules/<owner>`; route screens compose
  module components and import only module public/API surfaces.
