# NovelWiki module ownership

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

Cross-module executable dependencies are injected behind consumer-owned ports. Atomic multi-writer
operations live in `novelwiki/workflows`; router, CLI, and worker adapters do not own transactions
or SQL.
