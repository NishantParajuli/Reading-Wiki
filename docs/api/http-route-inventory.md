# Exact HTTP route inventory

> **Generated reference:** `tests/contracts/snapshots/routes.json` is the source of
> truth. This page renders every contracted method/path/endpoint-name tuple for
> searchability and review. For behavior, authorization, CSRF, and module ownership, see
> [http-api.md](http-api.md). After changing routes, run
> `uv run python scripts/contracts.py --update` and update this table in the same change.

Current snapshot: **119 routes**. FastAPI-generated documentation routes and the
Platform health endpoint are included; the SPA catch-all is not an HTTP contract row.

| Method | Exact path | FastAPI endpoint name |
|---|---|---|
| `GET` | `/api/activity` | `api_activity` |
| `GET` | `/api/adapters` | `api_adapters` |
| `GET` | `/api/admin/ai/agy/health` | `admin_agy_health` |
| `POST` | `/api/admin/ai/agy/retry-waiting` | `admin_retry_waiting_agy` |
| `POST` | `/api/admin/ai/agy/smoke-test` | `admin_agy_smoke_test` |
| `GET` | `/api/admin/global-novels` | `admin_global_novels` |
| `GET` | `/api/admin/novels` | `admin_list_novels` |
| `GET` | `/api/admin/usage` | `admin_usage` |
| `GET` | `/api/admin/users` | `admin_list_users` |
| `DELETE` | `/api/admin/users/{user_id}` | `admin_delete_user` |
| `PATCH` | `/api/admin/users/{user_id}` | `admin_update_user` |
| `DELETE` | `/api/admin/users/{user_id}/ai-backend-policy` | `admin_delete_ai_backend_policy` |
| `GET` | `/api/admin/users/{user_id}/ai-backend-policy` | `admin_get_ai_backend_policy` |
| `PUT` | `/api/admin/users/{user_id}/ai-backend-policy` | `admin_put_ai_backend_policy` |
| `GET` | `/api/assets/import-jobs/{job_id}/{filename}` | `api_import_job_asset` |
| `GET` | `/api/assets/novels/{novel_id}/{filename}` | `api_novel_asset` |
| `POST` | `/api/auth/change-password` | `change_password` |
| `GET` | `/api/auth/links` | `oauth_links` |
| `POST` | `/api/auth/login` | `login` |
| `POST` | `/api/auth/logout` | `logout` |
| `GET` | `/api/auth/me` | `me` |
| `GET` | `/api/auth/oauth/{provider}/callback` | `oauth_callback` |
| `GET` | `/api/auth/oauth/{provider}/start` | `oauth_start` |
| `GET` | `/api/auth/providers` | `providers` |
| `POST` | `/api/auth/register` | `register` |
| `POST` | `/api/auth/request-reset` | `request_reset` |
| `POST` | `/api/auth/reset` | `reset_password` |
| `GET` | `/api/auth/verify` | `verify_email` |
| `POST` | `/api/auth/verify` | `verify_email_confirm` |
| `GET` | `/api/discover` | `api_discover` |
| `GET` | `/api/home` | `api_home` |
| `POST` | `/api/import/batch` | `api_import_batch` |
| `POST` | `/api/import/commit-series` | `api_import_commit_series` |
| `GET` | `/api/import/jobs` | `api_import_jobs` |
| `DELETE` | `/api/import/jobs/{job_id}` | `api_import_delete` |
| `GET` | `/api/import/jobs/{job_id}` | `api_import_job` |
| `POST` | `/api/import/jobs/{job_id}/cancel` | `api_import_cancel` |
| `POST` | `/api/import/jobs/{job_id}/commit` | `api_import_commit` |
| `POST` | `/api/import/jobs/{job_id}/confirm-ocr` | `api_import_confirm_ocr` |
| `PUT` | `/api/import/jobs/{job_id}/plan` | `api_import_update_plan` |
| `POST` | `/api/import/scan-incoming` | `api_import_scan_incoming` |
| `POST` | `/api/import/upload` | `api_import_upload` |
| `POST` | `/api/import/upload/init` | `api_import_upload_init` |
| `PUT` | `/api/import/upload/{job_id}/chunk` | `api_import_upload_chunk` |
| `POST` | `/api/import/upload/{job_id}/complete` | `api_import_upload_complete` |
| `GET` | `/api/import/upload/{job_id}/status` | `api_import_upload_status` |
| `GET` | `/api/jobs` | `api_list_jobs` |
| `GET` | `/api/jobs/{job_id}` | `api_get_job` |
| `POST` | `/api/jobs/{job_id}/cancel` | `api_cancel_job` |
| `PATCH` | `/api/me` | `api_update_me` |
| `POST` | `/api/me/avatar` | `api_upload_avatar` |
| `GET` | `/api/me/usage` | `api_my_usage` |
| `GET` | `/api/novels` | `api_list_novels` |
| `POST` | `/api/novels` | `api_create_novel` |
| `DELETE` | `/api/novels/{novel_id}` | `api_delete_novel` |
| `GET` | `/api/novels/{novel_id}` | `api_get_novel` |
| `PATCH` | `/api/novels/{novel_id}` | `api_update_novel` |
| `POST` | `/api/novels/{novel_id}/ask` | `ask_question` |
| `GET` | `/api/novels/{novel_id}/audio/chapters` | `api_novel_audio_chapters` |
| `GET` | `/api/novels/{novel_id}/audio/coverage` | `api_novel_audio_coverage` |
| `POST` | `/api/novels/{novel_id}/audiobook` | `api_generate_book_audio` |
| `GET` | `/api/novels/{novel_id}/audiobook/status` | `api_book_audio_status` |
| `GET` | `/api/novels/{novel_id}/bookmarks` | `api_list_bookmarks` |
| `POST` | `/api/novels/{novel_id}/bookmarks` | `api_add_bookmark` |
| `DELETE` | `/api/novels/{novel_id}/bookmarks/{bookmark_id}` | `api_delete_bookmark` |
| `GET` | `/api/novels/{novel_id}/chapter/{number}` | `api_get_chapter` |
| `POST` | `/api/novels/{novel_id}/chapter/{number}/audio` | `api_generate_chapter_audio` |
| `GET` | `/api/novels/{novel_id}/chapter/{number}/audio.opus` | `api_get_chapter_audio` |
| `GET` | `/api/novels/{novel_id}/chapter/{number}/audio/status` | `api_chapter_audio_status` |
| `PUT` | `/api/novels/{novel_id}/chapter/{number}/content` | `api_edit_base_content` |
| `POST` | `/api/novels/{novel_id}/chapter/{number}/contribute` | `api_contribute` |
| `DELETE` | `/api/novels/{novel_id}/chapter/{number}/overlay` | `api_delete_overlay` |
| `PUT` | `/api/novels/{novel_id}/chapter/{number}/overlay` | `api_save_overlay` |
| `POST` | `/api/novels/{novel_id}/chapter/{number}/resolve` | `api_resolve_overlay` |
| `POST` | `/api/novels/{novel_id}/chapter/{number}/self-translate` | `api_self_translate` |
| `GET` | `/api/novels/{novel_id}/chapters` | `api_list_chapters` |
| `POST` | `/api/novels/{novel_id}/codex/build` | `api_codex_build` |
| `GET` | `/api/novels/{novel_id}/contributions` | `api_list_contributions` |
| `POST` | `/api/novels/{novel_id}/contributions/{contribution_id}/accept` | `api_accept_contribution` |
| `POST` | `/api/novels/{novel_id}/contributions/{contribution_id}/reject` | `api_reject_contribution` |
| `GET` | `/api/novels/{novel_id}/cost-estimate` | `api_cost_estimate` |
| `POST` | `/api/novels/{novel_id}/cover` | `api_upload_novel_cover` |
| `GET` | `/api/novels/{novel_id}/entities` | `api_list_entities` |
| `GET` | `/api/novels/{novel_id}/entity/resolve` | `api_resolve_entity` |
| `GET` | `/api/novels/{novel_id}/entity/{entity_id}` | `api_get_entity_profile` |
| `GET` | `/api/novels/{novel_id}/entity/{entity_id}/identities` | `api_get_identities` |
| `GET` | `/api/novels/{novel_id}/entity/{entity_id}/relationships` | `api_get_relationships` |
| `GET` | `/api/novels/{novel_id}/entity/{entity_id}/timeline` | `api_get_timeline` |
| `GET` | `/api/novels/{novel_id}/glossary` | `api_list_glossary` |
| `PUT` | `/api/novels/{novel_id}/glossary` | `api_upsert_glossary` |
| `POST` | `/api/novels/{novel_id}/glossary/seed` | `api_seed_glossary` |
| `DELETE` | `/api/novels/{novel_id}/glossary/{term_id}` | `api_delete_glossary` |
| `GET` | `/api/novels/{novel_id}/health` | `api_novel_health` |
| `DELETE` | `/api/novels/{novel_id}/library` | `api_remove_from_library` |
| `POST` | `/api/novels/{novel_id}/library` | `api_add_to_library` |
| `POST` | `/api/novels/{novel_id}/merge-entities` | `trigger_merge` |
| `GET` | `/api/novels/{novel_id}/meta` | `api_meta_chapters` |
| `GET` | `/api/novels/{novel_id}/progress` | `api_get_progress` |
| `PUT` | `/api/novels/{novel_id}/progress` | `api_set_progress` |
| `POST` | `/api/novels/{novel_id}/recap` | `api_recap` |
| `POST` | `/api/novels/{novel_id}/scrape` | `api_scrape` |
| `POST` | `/api/novels/{novel_id}/sources` | `api_add_source` |
| `PATCH` | `/api/novels/{novel_id}/sources/{source_id}` | `api_update_source` |
| `GET` | `/api/novels/{novel_id}/stats` | `api_meta_stats` |
| `GET` | `/api/novels/{novel_id}/tag-suggestions` | `api_list_tag_suggestions` |
| `POST` | `/api/novels/{novel_id}/tag-suggestions` | `api_suggest_tags` |
| `POST` | `/api/novels/{novel_id}/tag-suggestions/{suggestion_id}/accept` | `api_accept_tag_suggestion` |
| `POST` | `/api/novels/{novel_id}/tag-suggestions/{suggestion_id}/reject` | `api_reject_tag_suggestion` |
| `POST` | `/api/novels/{novel_id}/translate` | `api_translate` |
| `PATCH` | `/api/novels/{novel_id}/visibility` | `api_set_visibility` |
| `GET` | `/api/tts/jobs/{job_id}` | `api_tts_job` |
| `POST` | `/api/tts/jobs/{job_id}/cancel` | `api_cancel_tts_job` |
| `GET` | `/api/tts/voices` | `api_tts_voices` |
| `GET` | `/api/users/{username}` | `api_user_profile` |
| `GET` | `/docs` | `swagger_ui_html` |
| `GET` | `/docs/oauth2-redirect` | `swagger_ui_redirect` |
| `GET` | `/health` | `health_check` |
| `GET` | `/openapi.json` | `openapi` |
| `GET` | `/redoc` | `redoc_html` |
