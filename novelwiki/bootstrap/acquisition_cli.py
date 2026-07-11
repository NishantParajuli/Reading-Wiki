"""Composition root for Acquisition CLI application commands."""
from __future__ import annotations


class AcquisitionCliGateway:
    async def safe_url(self, url):
        from novelwiki.modules.acquisition.application.commands import UnsafeSourceError
        from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import (
            SafeFetchError,
            validate_source_start_url,
        )
        try:
            return await validate_source_start_url(url)
        except SafeFetchError as exc:
            raise UnsafeSourceError(str(exc)) from exc

    async def create_novel(self, **fields):
        from novelwiki.bootstrap.cli_services import create_system_novel_from_cli
        return await create_system_novel_from_cli(**fields)

    async def scrape_source(self, source_id, **fields):
        from novelwiki.modules.acquisition.adapters.outbound.scraper.runner import scrape_source
        return await scrape_source(source_id, **fields)

    async def scrape_novel(self, novel_id, **fields):
        from novelwiki.modules.acquisition.adapters.outbound.scraper.runner import scrape_novel
        return await scrape_novel(novel_id, **fields)

    def ensure_storage(self):
        from novelwiki.modules.acquisition.adapters.outbound.importer.storage import ensure_dirs
        ensure_dirs()

    async def create_job(self, fmt, path, options, status):
        from novelwiki.modules.acquisition.adapters.inbound.worker import create_job
        return await create_job(fmt, path, options=options, status=status)

    def parse(self, fmt, path, job_id):
        if fmt == "epub":
            from novelwiki.modules.acquisition.adapters.outbound.importer.parsers.epub import parse_epub
            return parse_epub(path, job_id)
        from novelwiki.modules.acquisition.adapters.outbound.importer.parsers.pdf_text import parse_pdf_text
        return parse_pdf_text(path, job_id)

    def clean(self, document):
        from novelwiki.modules.acquisition.domain.cleanup import clean_document
        clean_document(document)

    def save_blocks(self, job_id, document):
        from novelwiki.modules.acquisition.adapters.outbound.importer.storage import save_blocks
        save_blocks(job_id, document)

    def plan(self, document):
        from novelwiki.modules.acquisition.adapters.outbound.importer.segment import build_plan
        return build_plan(document)

    def quality(self, document, plan):
        from novelwiki.modules.acquisition.domain.quality import compute_quality
        return compute_quality(document, plan)

    async def update_job(self, job_id, **fields):
        from novelwiki.modules.acquisition.adapters.inbound.worker import update_job
        await update_job(job_id, **fields)

    async def get_job(self, job_id):
        from novelwiki.modules.acquisition.adapters.inbound.worker import get_job
        return await get_job(job_id)

    async def commit_job(self, job):
        from novelwiki.modules.acquisition.adapters.outbound.importer.commit import commit_job
        return await commit_job(job)

    async def commit_series(self, job_ids):
        from novelwiki.modules.acquisition.adapters.outbound.importer.commit import commit_series
        return await commit_series(job_ids)

    async def build_codex(self, novel_id, start, end):
        from novelwiki.modules.codex.adapters.outbound.ingest.chunk import chunk_all_chapters
        from novelwiki.modules.codex.adapters.outbound.ingest.embed import embed_missing_chunks
        from novelwiki.modules.codex.adapters.outbound.ingest.extract import extract_all_chapters
        from novelwiki.modules.codex.adapters.outbound.retrieval.bm25 import get_bm25_manager
        await chunk_all_chapters(novel_id, force=False, from_chapter=start, to_chapter=end)
        await embed_missing_chunks(novel_id, from_chapter=start, to_chapter=end)
        await extract_all_chapters(novel_id, force=False, from_chapter=start, to_chapter=end)
        await get_bm25_manager(novel_id).rebuild()


def build_acquisition_commands():
    from novelwiki.modules.acquisition.application.commands import AcquisitionCommands
    return AcquisitionCommands(AcquisitionCliGateway())


async def run_standalone_import_worker(output):
    """Bootstrap owns standalone worker lifecycle; Typer only selects the command."""
    import asyncio
    from novelwiki.modules.acquisition.adapters.inbound.worker import worker_loop, stop_worker
    output("Import worker running (Ctrl-C to stop)…")
    try:
        await worker_loop()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await stop_worker()
