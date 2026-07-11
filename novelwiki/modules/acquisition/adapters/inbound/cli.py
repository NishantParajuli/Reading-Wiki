import asyncio
import logging

import typer

from novelwiki.db.connection import close_db_pool
from novelwiki.scraper.runner import scrape_novel, scrape_source
from novelwiki.scraper.safe_fetch import SafeFetchError, validate_source_start_url

logging.getLogger("httpx").setLevel(logging.WARNING)
app = typer.Typer()

@app.command()
def add_novel(
    title: str = typer.Argument(..., help="Novel title"),
    start_url: str = typer.Argument(..., help="Starting chapter URL of the first source"),
    adapter: str = typer.Option("fenrirealm", "--adapter", "-a", help="Scraper adapter key (see `adapters` in scraper/adapters.py)"),
    language: str = typer.Option("en", "--lang", "-l", help="Source language code"),
    is_raw: bool = typer.Option(False, "--raw", help="Source is raw (foreign-language; needs translation)"),
    chapter_offset: float = typer.Option(0.0, "--offset", help="Add this to source-local numbers to get global chapter numbers"),
    codex: bool = typer.Option(False, "--codex", help="Enable the spoiler-safe codex for this novel"),
):
    """Creates a novel in the library plus its first source, and prints the new ids."""
    async def run():
        try:
            safe_start_url = await validate_source_start_url(start_url)
        except SafeFetchError as e:
            typer.secho(f"Unsafe source URL: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        from novelwiki.bootstrap.cli_services import create_system_novel_from_cli
        novel_id, source_id = await create_system_novel_from_cli(
            title=title, codex_enabled=codex, language=language,
            adapter=adapter, start_url=safe_start_url,
            is_raw=is_raw, chapter_offset=chapter_offset,
        )
        typer.echo(typer.style(f"✔ Created novel id={novel_id}, source id={source_id}.", fg=typer.colors.GREEN, bold=True))
        typer.echo(f"  Next: novelwiki scrape {novel_id} --max 5")
        await close_db_pool()
    asyncio.run(run())


@app.command()
def scrape(
    novel_id: int = typer.Argument(..., help="The novel id to scrape (all its sources)"),
    source_id: int = typer.Option(None, "--source", "-s", help="Scrape only this source id"),
    force: bool = typer.Option(False, "--force", "-f", help="Force scrape already existing chapters"),
    max_chapters: int = typer.Option(None, "--max", "-m", help="Maximum number of chapters to scrape in this run")
):
    """Scrapes a novel's sources chapter by chapter (stops cleanly at premium)."""
    async def run():
        if source_id is not None:
            typer.echo(f"Scraping source {source_id}...")
            count = await scrape_source(source_id, force=force, max_chapters=max_chapters, expected_novel_id=novel_id)
        else:
            typer.echo(f"Scraping all sources of novel {novel_id}...")
            count = await scrape_novel(novel_id, force=force, max_chapters=max_chapters)
        typer.echo(typer.style(f"✔ Successfully scraped {count} chapters.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command(name="import")
def import_file(
    path: str = typer.Argument(..., help="Path to an .epub or digital .pdf file to import"),
    novel_id: int = typer.Option(None, "--novel", "-n", help="Append to this existing novel id (omit to create a new novel)"),
    offset: float = typer.Option(0.0, "--offset", help="Append: add this to segment chapter numbers to get global numbers"),
    codex: bool = typer.Option(False, "--codex", help="Build the codex over the imported range after committing"),
):
    """Imports an EPUB or digital PDF into the library from the terminal (parse → segment →
    commit), mirroring the web import worker. Heuristic segmentation only (no interactive
    review). Scanned PDFs need the OCR confirm gate — import those from the web UI."""
    import os
    ext = os.path.splitext(path)[1].lower()
    if not os.path.isfile(path):
        typer.echo(typer.style(f"✘ File not found: {path}", fg=typer.colors.RED, bold=True))
        raise typer.Exit(1)
    if ext not in (".epub", ".pdf"):
        typer.echo(typer.style("✘ Only .epub and .pdf files are supported.", fg=typer.colors.RED, bold=True))
        raise typer.Exit(1)
    fmt = "epub" if ext == ".epub" else "pdf"

    async def run():
        from novelwiki.importer import jobs as import_jobs, storage, cleanup, segment, commit

        storage.ensure_dirs()
        target = {"novel_id": novel_id, "offset": offset} if novel_id else "new"
        job_id = await import_jobs.create_job(fmt, os.path.abspath(path),
                                              options={"target": target}, status="receiving")
        typer.echo(f"Parsing {path} (job {job_id})…")
        if fmt == "epub":
            from novelwiki.importer.parsers import epub as epub_parser
            document = epub_parser.parse_epub(path, job_id)
        else:
            from novelwiki.importer.parsers import pdf_text
            document = pdf_text.parse_pdf_text(path, job_id)
            if document.meta.get("scanned"):
                typer.echo(typer.style(
                    "✘ This PDF is scanned and needs OCR (cost-confirmed). Import it from the web UI.",
                    fg=typer.colors.RED, bold=True))
                await close_db_pool()
                raise typer.Exit(1)
        cleanup.clean_document(document)
        storage.save_blocks(job_id, document)
        plan = segment.build_plan(document)
        await import_jobs.update_job(job_id, plan=plan, detected_meta={"title": document.meta.get("title")})

        included = [s for s in plan["segments"] if s.get("include")]
        typer.echo(f"  {len(plan['segments'])} segments detected, {len(included)} will be imported.")

        job = await import_jobs.get_job(job_id)
        result = await commit.commit_job(job)
        await import_jobs.update_job(job_id, status="committed", novel_id=result["novel_id"],
                                     source_id=result.get("source_id"))
        st = result["stats"]
        typer.echo(typer.style(
            f"✔ Imported {st['chapters_written']} chapters (ch. {st['from_chapter']}–{st['to_chapter']}) "
            f"into novel {result['novel_id']}.", fg=typer.colors.GREEN, bold=True))

        if codex:
            from novelwiki.ingest.chunk import chunk_all_chapters
            from novelwiki.ingest.embed import embed_missing_chunks
            from novelwiki.ingest.extract import extract_all_chapters
            from novelwiki.retrieval.bm25 import get_bm25_manager
            nid, frm, to = result["novel_id"], st["from_chapter"], st["to_chapter"]
            typer.echo("Building codex over the imported range (chunk → embed → extract)…")
            await chunk_all_chapters(nid, force=False, from_chapter=frm, to_chapter=to)
            await embed_missing_chunks(nid, from_chapter=frm, to_chapter=to)
            await extract_all_chapters(nid, force=False, from_chapter=frm, to_chapter=to)
            await get_bm25_manager(nid).rebuild()
            typer.echo(typer.style("✔ Codex built.", fg=typer.colors.GREEN, bold=True))

        await close_db_pool()
    asyncio.run(run())


async def _parse_into_job(path: str, fmt: str, options: dict | None = None) -> int:
    """Create a job, parse + clean + segment the file, and leave it at 'awaiting_review' (the
    same state the web worker reaches). Returns the job id. Scanned PDFs are rejected (OCR
    needs the cost-confirm gate / a running worker). Shared by the batch/series CLI commands."""
    import os
    from novelwiki.importer import jobs as import_jobs, storage, cleanup, segment, quality
    storage.ensure_dirs()
    job_id = await import_jobs.create_job(fmt, os.path.abspath(path),
                                          options=options or {}, status="receiving")
    if fmt == "epub":
        from novelwiki.importer.parsers import epub as epub_parser
        document = epub_parser.parse_epub(path, job_id)
    else:
        from novelwiki.importer.parsers import pdf_text
        document = pdf_text.parse_pdf_text(path, job_id)
        if document.meta.get("scanned"):
            raise RuntimeError(f"{os.path.basename(path)} is a scanned PDF — import it from the web UI (OCR).")
    cleanup.clean_document(document)
    storage.save_blocks(job_id, document)
    plan = segment.build_plan(document)
    await import_jobs.update_job(
        job_id, plan=plan, status="awaiting_review",
        detected_meta={"title": document.meta.get("title"), "series": document.meta.get("series"),
                       "series_index": document.meta.get("series_index")},
        stats={"quality": quality.compute_quality(document, plan)},
    )
    return job_id


def _import_files_in(folder: str) -> list[str]:
    import os
    out = []
    for dirpath, _dirs, files in os.walk(folder):
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in (".epub", ".pdf"):
                out.append(os.path.join(dirpath, name))
    return out


async def _build_codex_range(novel_id: int, frm: float, to: float):
    from novelwiki.ingest.embed import embed_missing_chunks
    from novelwiki.ingest.extract import extract_all_chapters
    await chunk_all_chapters(novel_id, force=False, from_chapter=frm, to_chapter=to)
    await embed_missing_chunks(novel_id, from_chapter=frm, to_chapter=to)
    await extract_all_chapters(novel_id, force=False, from_chapter=frm, to_chapter=to)
    await get_bm25_manager(novel_id).rebuild()


@app.command(name="import-batch")
def import_batch(
    folder: str = typer.Argument(..., help="Folder to scan recursively for .epub/.pdf (e.g. a Calibre library)"),
    series: bool = typer.Option(False, "--series", help="Group EPUB volumes that share a series into single novels"),
    codex: bool = typer.Option(False, "--codex", help="Build the codex over each imported novel afterward"),
):
    """Bulk-imports every EPUB/digital-PDF under a folder. With --series, books sharing a
    detected series become one multi-volume novel; otherwise each book becomes its own novel."""
    import os
    if not os.path.isdir(folder):
        typer.echo(typer.style(f"✘ Not a directory: {folder}", fg=typer.colors.RED, bold=True)); raise typer.Exit(1)
    files = _import_files_in(folder)
    if not files:
        typer.echo(typer.style("✘ No .epub/.pdf files found.", fg=typer.colors.RED, bold=True)); raise typer.Exit(1)

    async def run():
        from novelwiki.importer import jobs as import_jobs, commit
        typer.echo(f"Found {len(files)} file(s). Parsing…")
        parsed = []   # (job_id, series_name)
        for p in files:
            fmt = "epub" if p.lower().endswith(".epub") else "pdf"
            try:
                jid = await _parse_into_job(p, fmt)
                job = await import_jobs.get_job(jid)
                parsed.append((jid, (job.get("detected_meta") or {}).get("series")))
                typer.echo(f"  ✓ {os.path.basename(p)}")
            except Exception as e:
                typer.echo(typer.style(f"  ✘ {os.path.basename(p)}: {e}", fg=typer.colors.YELLOW))

        novels = []
        if series:
            groups: dict = {}
            for jid, sname in parsed:
                groups.setdefault(sname or f"__single_{jid}", []).append(jid)
            for key, ids in groups.items():
                if key.startswith("__single_") or len(ids) == 1:
                    res = await commit.commit_job(await import_jobs.get_job(ids[0]))
                    novels.append(res)
                else:
                    res = await commit.commit_series(ids)
                    novels.append(res)
                    typer.echo(f"  → series '{key}': {len(ids)} volumes → novel {res['novel_id']}")
        else:
            for jid, _s in parsed:
                novels.append(await commit.commit_job(await import_jobs.get_job(jid)))

        typer.echo(typer.style(f"✔ Imported {len(novels)} novel(s).", fg=typer.colors.GREEN, bold=True))
        if codex:
            for res in novels:
                st = res.get("stats", {})
                if st.get("from_chapter") is not None:
                    typer.echo(f"Building codex for novel {res['novel_id']}…")
                    await _build_codex_range(res["novel_id"], st["from_chapter"], st["to_chapter"])
            typer.echo(typer.style("✔ Codex built.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command(name="import-series")
def import_series(
    paths: list[str] = typer.Argument(..., help="EPUB/PDF volumes to fold into one novel (ordered by detected series index)"),
    codex: bool = typer.Option(False, "--codex", help="Build the codex over the new novel afterward"),
):
    """Imports several volumes as a single multi-volume novel (one source per volume)."""
    import os
    for p in paths:
        if not os.path.isfile(p):
            typer.echo(typer.style(f"✘ File not found: {p}", fg=typer.colors.RED, bold=True)); raise typer.Exit(1)

    async def run():
        from novelwiki.importer import commit
        job_ids = []
        for p in paths:
            fmt = "epub" if p.lower().endswith(".epub") else "pdf"
            job_ids.append(await _parse_into_job(p, fmt))
            typer.echo(f"  ✓ parsed {os.path.basename(p)}")
        res = await commit.commit_series(job_ids)
        st = res["stats"]
        typer.echo(typer.style(
            f"✔ Imported {res['volumes']} volumes (ch. {st['from_chapter']}–{st['to_chapter']}) "
            f"into novel {res['novel_id']}.", fg=typer.colors.GREEN, bold=True))
        if codex:
            typer.echo("Building codex…")
            await _build_codex_range(res["novel_id"], st["from_chapter"], st["to_chapter"])
            typer.echo(typer.style("✔ Codex built.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command(name="import-worker")
def import_worker():
    """Runs the durable import worker as a standalone process (parse/OCR/commit jobs from the
    DB queue). Use this to split the worker off the web image; Ctrl-C stops it cleanly."""
    async def run():
        from novelwiki.importer.jobs import worker_loop, stop_worker
        from novelwiki.db.connection import init_db_pool
        await init_db_pool()
        typer.echo("Import worker running (Ctrl-C to stop)…")
        try:
            await worker_loop()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await stop_worker()
            await close_db_pool()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        typer.echo("Stopped.")


