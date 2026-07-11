"""Stable direct-call exports backed exclusively by native module adapters.

FastAPI registers the native routers in ``platform.web.app``. This module remains only for
older Python callers and evaluation fixtures; it contains no route registry, SQL, or workflow.
"""
from __future__ import annotations

import inspect
from functools import wraps

from novelwiki import quota
from novelwiki.agent.orchestrator import answer_question
from novelwiki.retrieval.bm25 import get_bm25_manager

from novelwiki.modules.acquisition.adapters.inbound import http as acquisition
from novelwiki.modules.catalog.adapters.inbound import http as catalog
from novelwiki.modules.codex.adapters.inbound import http as codex
from novelwiki.modules.experience.adapters.inbound import projections_http as experience
from novelwiki.modules.reading.adapters.inbound import http as reading
from novelwiki.modules.translation.adapters.inbound import http as translation
from novelwiki.modules.work.adapters.inbound import http as work

# Request/response models retained as stable import names.
SourceCreate = acquisition.SourceCreate
SourceUpdate = acquisition.SourceUpdate
ScrapeTrigger = acquisition.ScrapeTrigger
PlanUpdate = acquisition.PlanUpdate
ImportCommit = acquisition.ImportCommit
OcrConfirm = acquisition.OcrConfirm
ImportInit = acquisition.ImportInit
ImportBatch = acquisition.ImportBatch
CommitSeries = acquisition.CommitSeries
NovelCreate = catalog.NovelCreate
NovelUpdate = catalog.NovelUpdate
VisibilityUpdate = catalog.VisibilityUpdate
TagSuggestion = catalog.TagSuggestion
ProgressUpdate = reading.ProgressUpdate
BookmarkCreate = reading.BookmarkCreate
OverlayUpdate = reading.OverlayUpdate
ResolveOverlay = reading.ResolveOverlay
ContributionAccept = reading.ContributionAccept
TranslateTrigger = translation.TranslateTrigger
GlossaryUpsert = translation.GlossaryUpsert
AskRequest = codex.AskRequest
CodexBuild = codex.CodexBuild
MergePayload = codex.MergePayload
Citation = codex.Citation
AskResponse = codex.AskResponse

_CATALOG_MIGRATION = {
    "api_create_novel", "api_upload_novel_cover", "api_delete_novel",
    "api_suggest_tags", "api_list_tag_suggestions", "api_accept_tag_suggestion",
    "api_reject_tag_suggestion",
}
_ACQUISITION_IMPORT = {
    name for name in dir(acquisition)
    if name.startswith("api_import_") and name != "api_import_job_asset"
}
_READING_PERSONAL = {
    "api_get_progress", "api_set_progress", "api_list_bookmarks",
    "api_add_bookmark", "api_delete_bookmark",
}


async def _invoke(handler, *args, **kwargs):
    module = handler.__module__
    parameters = inspect.signature(handler).parameters
    name = handler.__name__
    if module == catalog.__name__ and "service" in parameters:
        if name in _CATALOG_MIGRATION:
            from novelwiki.bootstrap.catalog import build_catalog_migration_service
            kwargs.setdefault("service", await build_catalog_migration_service())
        else:
            from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
            from novelwiki.modules.catalog.application import CatalogAccessService
            from novelwiki.platform.database import init_db_pool
            kwargs.setdefault("service", CatalogAccessService(PostgresCatalogRepository(await init_db_pool())))
    elif module == acquisition.__name__:
        from novelwiki.bootstrap.acquisition import build_adapter_catalog_query
        from novelwiki.bootstrap.acquisition_routes import (
            build_acquisition_principal_factory, build_acquisition_service,
            build_import_service,
        )
        if "query" in parameters:
            kwargs.setdefault("query", build_adapter_catalog_query())
        if "service" in parameters:
            builder = build_import_service if name in _ACQUISITION_IMPORT else build_acquisition_service
            kwargs.setdefault("service", await builder())
        if "principal_factory" in parameters:
            kwargs.setdefault("principal_factory", build_acquisition_principal_factory())
    elif module == reading.__name__ and "service" in parameters:
        if name in _READING_PERSONAL:
            from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
            from novelwiki.modules.catalog.application import CatalogAccessService
            from novelwiki.modules.reading.adapters.outbound.postgres import PostgresReadingRepository
            from novelwiki.modules.reading.application import ReadingService
            from novelwiki.platform.database import init_db_pool
            pool = await init_db_pool()
            kwargs.setdefault(
                "service",
                ReadingService(
                    PostgresReadingRepository(pool),
                    CatalogAccessService(PostgresCatalogRepository(pool)),
                ),
            )
        else:
            from novelwiki.bootstrap.reading_migration import build_reading_migration_service
            kwargs.setdefault("service", await build_reading_migration_service())
    elif module == translation.__name__:
        from novelwiki.bootstrap.translation import (
            build_glossary_service, build_translation_scheduling_service,
        )
        from novelwiki.modules.identity.adapters.principals import principal_from_user
        if "service" in parameters:
            builder = build_translation_scheduling_service if name == "api_translate" else build_glossary_service
            kwargs.setdefault("service", await builder())
        if "principal_factory" in parameters:
            kwargs.setdefault("principal_factory", principal_from_user)
    elif module == codex.__name__:
        from novelwiki.bootstrap.codex_migration import (
            build_codex_migration_service, codex_principal_from_user,
        )
        service = await build_codex_migration_service()
        if name == "ask_question":
            base = service.queries._agent

            class DirectCallAgent:
                def __getattr__(self, attribute):
                    return getattr(base, attribute)

                async def ensure_index(self, novel_id):
                    await get_bm25_manager(novel_id).ensure_loaded()

                async def answer(self, novel_id, question, ceiling):
                    return await answer_question(novel_id, question, ceiling.value)

            service.queries._agent = DirectCallAgent()
        kwargs.setdefault("service", service)
        kwargs.setdefault("principal_factory", codex_principal_from_user)
    elif module == experience.__name__ and "service" in parameters:
        from novelwiki.bootstrap.experience import build_experience_projection_service
        kwargs.setdefault("service", await build_experience_projection_service())
    result = await handler(*args, **kwargs)
    if module == codex.__name__ and name == "ask_question" and isinstance(result, dict):
        return codex.AskResponse(**result)
    return result


def _direct(handler):
    @wraps(handler)
    async def invoke(*args, **kwargs):
        return await _invoke(handler, *args, **kwargs)
    return invoke


for _module in (acquisition, catalog, codex, experience, reading, translation, work):
    for _name in dir(_module):
        if _name.startswith("api_") or _name in {"ask_question", "trigger_merge"}:
            globals()[_name] = _direct(getattr(_module, _name))

del _module, _name
