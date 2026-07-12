"""Composition wiring for durable Acquisition adapters."""

from __future__ import annotations


def wire_acquisition_runtime() -> None:
    from novelwiki.modules.acquisition.application.runtime_dependencies import (
        configure_runtime,
    )

    class Runtime:
        async def import_repository(self):
            from novelwiki.bootstrap.acquisition import build_import_worker_repository
            return await build_import_worker_repository()

        async def owner_can_spend(self, user_id):
            from novelwiki.bootstrap.acquisition import import_worker_owner_can_spend
            return await import_worker_owner_can_spend(user_id)

        async def novel_titles(self, novel_ids):
            from novelwiki.bootstrap.acquisition import import_job_novel_titles
            return await import_job_novel_titles(novel_ids)

        async def gemini_budget_remaining(self):
            from novelwiki.bootstrap.acquisition import gemini_budget_remaining
            return await gemini_budget_remaining()

        def bind_commit_apis(self, connection):
            from novelwiki.bootstrap.acquisition_routes import bind_import_commit_apis
            return bind_import_commit_apis(connection)

        async def commit_uow_factory(self):
            from novelwiki.bootstrap.acquisition_routes import build_import_commit_uow_factory
            return await build_import_commit_uow_factory()

        async def reserve_auto_codex(self, user_id):
            from novelwiki.bootstrap.acquisition_routes import reserve_auto_codex
            return await reserve_auto_codex(user_id)

        async def schedule_codex(self, novel_id, start, end, user_id):
            from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
                PostgresQuotaRepository,
            )
            from novelwiki.modules.identity.application import QuotaService
            from novelwiki.modules.work.adapters.outbound import postgres as work
            from novelwiki.platform.database import init_db_pool

            try:
                _job_id, created = await work.create_job(
                    "codex_build", novel_id=novel_id, user_id=user_id,
                    options={"force": False, "from_chapter": start, "to_chapter": end},
                    quota_kind="codex_builds",
                    quota_reserved=(1 if user_id is not None else 0),
                )
                if not created and user_id is not None:
                    await QuotaService(
                        PostgresQuotaRepository(pool=await init_db_pool())
                    ).refund(user_id, "codex_builds", 1)
            except Exception:
                if user_id is not None:
                    await QuotaService(
                        PostgresQuotaRepository(pool=await init_db_pool())
                    ).refund(user_id, "codex_builds", 1)
                raise

        async def import_job(self, job_id):
            from novelwiki.modules.acquisition.application import import_worker
            return await import_worker.get_job(job_id)

        @staticmethod
        async def _reading():
            from novelwiki.modules.reading.adapters.outbound.ingestion import (
                PostgresReadingIngestionGateway,
            )
            from novelwiki.platform.database import init_db_pool
            return PostgresReadingIngestionGateway(await init_db_pool())

        async def upsert_ingested_chapter(self, source, number, chapter, force):
            return await (await self._reading()).upsert_ingested_chapter(
                source, number, chapter, force
            )

        async def resume_url(self, source_id):
            return await (await self._reading()).resume_url(source_id)

        async def update_source_offset(self, source_id, offset):
            from novelwiki.bootstrap.acquisition_routes import build_import_commit_uow_factory
            from novelwiki.workflows.update_source_offset import update_source_offset
            return await update_source_offset(
                await build_import_commit_uow_factory(), source_id, offset
            )

        async def call_llm(self, *args, **kwargs):
            from novelwiki.modules.ai_execution.adapters.outbound.providers import call_llm
            return await call_llm(*args, **kwargs)

        async def call_vision(self, *args, **kwargs):
            from novelwiki.modules.ai_execution.adapters.outbound.providers import (
                call_vision_completion,
            )
            return await call_vision_completion(*args, **kwargs)

        def ensure_import_dirs(self):
            from novelwiki.modules.acquisition.adapters.outbound.importer import storage
            storage.ensure_dirs()

        def save_blocks(self, job_id, document):
            from novelwiki.modules.acquisition.adapters.outbound.importer import storage
            storage.save_blocks(job_id, document)

        def staged_asset_url(self, job_id, sha, extension):
            from novelwiki.modules.acquisition.adapters.outbound.importer import storage
            return storage.staged_asset_url(job_id, sha, extension)

        def cleanup_import_job(self, job_id):
            from novelwiki.modules.acquisition.adapters.outbound.importer import storage
            storage.cleanup_job(job_id)

        def parse_epub(self, path, job_id):
            from novelwiki.modules.acquisition.adapters.outbound.importer.parsers.epub import parse_epub
            return parse_epub(path, job_id)

        def parse_pdf_text(self, path, job_id):
            from novelwiki.modules.acquisition.adapters.outbound.importer.parsers.pdf_text import parse_pdf_text
            return parse_pdf_text(path, job_id)

        def build_segment_plan(self, document):
            from novelwiki.modules.acquisition.adapters.outbound.importer.segment import build_plan
            return build_plan(document)

        async def refine_segment_plan(self, plan, document):
            from novelwiki.modules.acquisition.adapters.outbound.importer.segment import refine_plan
            return await refine_plan(plan, document)

        async def commit_series(self, job_ids):
            from novelwiki.modules.acquisition.adapters.outbound.importer.commit import commit_series
            return await commit_series(job_ids)

        def estimate_ocr_cost(self, pages, gemini_first, remaining):
            from novelwiki.modules.acquisition.adapters.outbound.importer.parsers.pdf_ocr import estimate_cost
            return estimate_cost(pages, gemini_first, remaining)

        async def parse_pdf_ocr(self, path, job_id, options, progress):
            from novelwiki.modules.acquisition.adapters.outbound.importer.parsers.pdf_ocr import parse_pdf_ocr
            return await parse_pdf_ocr(path, job_id, options, progress)

        async def commit_job(self, job):
            from novelwiki.modules.acquisition.adapters.outbound.importer.commit import commit_job
            return await commit_job(job)

    configure_runtime(Runtime())
