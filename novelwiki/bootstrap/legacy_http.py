"""Explicit ownership registry for handlers awaiting application-layer extraction.

The registered APIRoute objects retain their exact endpoint signatures and OpenAPI contracts,
but the aggregate legacy router is never mounted. Every bridge has one canonical module owner.
"""

from __future__ import annotations

from fastapi import APIRouter

from novelwiki.legacy.routes import router as legacy_router

OWNERS: dict[str, frozenset[str]] = {
    "identity": frozenset(),
    "catalog": frozenset(),
    "reading": frozenset({
        "api_list_chapters", "api_get_chapter", "api_edit_base_content",
        "api_save_overlay", "api_delete_overlay", "api_self_translate",
        "api_resolve_overlay", "api_contribute", "api_list_contributions",
        "api_accept_contribution", "api_reject_contribution",
    }),
    "acquisition": frozenset({
        "api_add_source", "api_update_source", "api_scrape",
        "api_novel_asset", "api_import_job_asset", "api_import_upload",
        "api_import_scan_incoming", "api_import_batch", "api_import_upload_init",
        "api_import_upload_status", "api_import_upload_chunk",
        "api_import_upload_complete", "api_import_commit_series",
        "api_import_jobs", "api_import_job", "api_import_update_plan",
        "api_import_commit", "api_import_confirm_ocr", "api_import_cancel",
        "api_import_delete",
    }),
    "translation": frozenset(),
    "codex": frozenset({
        "api_meta_chapters", "api_meta_stats", "api_list_entities",
        "api_resolve_entity", "api_get_entity_profile", "api_get_relationships",
        "api_get_timeline", "api_get_identities", "ask_question",
        "api_codex_build", "trigger_merge",
    }),
    "experience": frozenset(),
}

_route_by_name = {route.endpoint.__name__: route for route in legacy_router.routes}
_assigned = set().union(*OWNERS.values())
_available = set(_route_by_name)
if _assigned != _available:
    missing = sorted(_available - _assigned)
    unknown = sorted(_assigned - _available)
    raise RuntimeError(
        f"Legacy HTTP ownership registry drifted; missing={missing}, unknown={unknown}"
    )


def router_for(owner: str) -> APIRouter:
    names = OWNERS[owner]
    router = APIRouter()
    router.routes.extend(
        route for route in legacy_router.routes if route.endpoint.__name__ in names
    )
    return router
