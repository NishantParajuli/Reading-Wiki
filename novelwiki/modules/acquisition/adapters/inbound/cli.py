"""Typer transport for Acquisition application commands."""
from __future__ import annotations

from pathlib import Path

import typer

from novelwiki.platform.cli_runtime import run_cli

app = typer.Typer()

_command_factory = None
_standalone_worker = None


def configure_cli(command_factory, standalone_worker) -> None:
    global _command_factory, _standalone_worker
    _command_factory = command_factory
    _standalone_worker = standalone_worker


def _commands():
    if _command_factory is None:
        raise RuntimeError("Acquisition CLI commands were not wired by the composition root")
    return _command_factory()


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
            novel_id, source_id = await _commands().add_novel(
                title=title, codex_enabled=codex, language=language, adapter=adapter,
                start_url=start_url, is_raw=is_raw, chapter_offset=chapter_offset,
            )
        except Exception as exc:
            from novelwiki.modules.acquisition.application.commands import UnsafeSourceError
            if not isinstance(exc, UnsafeSourceError):
                raise
            typer.secho(f"Unsafe source URL: {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.echo(typer.style(
            f"✔ Created novel id={novel_id}, source id={source_id}.",
            fg=typer.colors.GREEN, bold=True,
        ))
        typer.echo(f"  Next: novelwiki scrape {novel_id} --max 5")
    run_cli(run())


@app.command()
def scrape(
    novel_id: int = typer.Argument(..., help="The novel id to scrape (all its sources)"),
    source_id: int = typer.Option(None, "--source", "-s", help="Scrape only this source id"),
    force: bool = typer.Option(False, "--force", "-f", help="Force scrape already existing chapters"),
    max_chapters: int = typer.Option(None, "--max", "-m", help="Maximum number of chapters to scrape in this run"),
):
    """Scrapes a novel's sources chapter by chapter (stops cleanly at premium)."""
    async def run():
        typer.echo(f"Scraping source {source_id}..." if source_id is not None
                   else f"Scraping all sources of novel {novel_id}...")
        count = await _commands().scrape(novel_id, source_id, force, max_chapters)
        typer.echo(typer.style(
            f"✔ Successfully scraped {count} chapters.", fg=typer.colors.GREEN, bold=True
        ))
    run_cli(run())


def _file_format(path: str) -> str:
    return "epub" if Path(path).suffix.lower() == ".epub" else "pdf"


def _require_import_file(path: str) -> None:
    candidate = Path(path)
    if not candidate.is_file():
        typer.echo(typer.style(f"✘ File not found: {path}", fg=typer.colors.RED, bold=True))
        raise typer.Exit(1)
    if candidate.suffix.lower() not in (".epub", ".pdf"):
        typer.echo(typer.style("✘ Only .epub and .pdf files are supported.", fg=typer.colors.RED, bold=True))
        raise typer.Exit(1)


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
    _require_import_file(path)

    async def run():
        typer.echo(f"Parsing {path}…")
        try:
            result = await _commands().import_file(path, _file_format(path), novel_id, offset, codex)
        except Exception as exc:
            from novelwiki.modules.acquisition.application.commands import ScannedPdfError
            if not isinstance(exc, ScannedPdfError):
                raise
            typer.echo(typer.style(
                "✘ This PDF is scanned and needs OCR (cost-confirmed). Import it from the web UI.",
                fg=typer.colors.RED, bold=True,
            ))
            raise typer.Exit(1)
        typer.echo(f"  {result['segments']} segments detected, {result['included']} will be imported.")
        stats = result["stats"]
        typer.echo(typer.style(
            f"✔ Imported {stats['chapters_written']} chapters (ch. {stats['from_chapter']}–{stats['to_chapter']}) "
            f"into novel {result['novel_id']}.", fg=typer.colors.GREEN, bold=True,
        ))
        if codex:
            typer.echo(typer.style("✔ Codex built.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())


def _import_files_in(folder: str) -> list[str]:
    return [str(path) for path in sorted(Path(folder).rglob("*"))
            if path.is_file() and path.suffix.lower() in (".epub", ".pdf")]


@app.command(name="import-batch")
def import_batch(
    folder: str = typer.Argument(..., help="Folder to scan recursively for .epub/.pdf (e.g. a Calibre library)"),
    series: bool = typer.Option(
        False, "--series",
        help="Group detected EPUB/PDF volumes that share a series into single novels",
    ),
    codex: bool = typer.Option(False, "--codex", help="Build the codex over each imported novel afterward"),
):
    """Bulk-imports every EPUB/digital-PDF under a folder. With --series, books sharing a
    detected series become one multi-volume novel; otherwise each book becomes its own novel."""
    if not Path(folder).is_dir():
        typer.echo(typer.style(f"✘ Not a directory: {folder}", fg=typer.colors.RED, bold=True))
        raise typer.Exit(1)
    files = _import_files_in(folder)
    if not files:
        typer.echo(typer.style("✘ No .epub/.pdf files found.", fg=typer.colors.RED, bold=True))
        raise typer.Exit(1)

    async def run():
        typer.echo(f"Found {len(files)} file(s). Parsing…")
        novels, errors = await _commands().import_batch(files, series, codex)
        failed = {path: error for path, error in errors}
        for path in files:
            if path in failed:
                typer.echo(typer.style(f"  ✘ {Path(path).name}: {failed[path]}", fg=typer.colors.YELLOW))
            else:
                typer.echo(f"  ✓ {Path(path).name}")
        for result in novels:
            if result.get("series_name"):
                typer.echo(f"  → series '{result['series_name']}': {result['volumes']} volumes → novel {result['novel_id']}")
        typer.echo(typer.style(f"✔ Imported {len(novels)} novel(s).", fg=typer.colors.GREEN, bold=True))
        if codex:
            typer.echo(typer.style("✔ Codex built.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())


@app.command(name="import-series")
def import_series(
    paths: list[str] = typer.Argument(..., help="EPUB/PDF volumes to fold into one novel (ordered by detected series index)"),
    codex: bool = typer.Option(False, "--codex", help="Build the codex over the new novel afterward"),
):
    """Imports several volumes as a single multi-volume novel (one source per volume)."""
    for path in paths:
        _require_import_file(path)

    async def run():
        result = await _commands().import_series(paths, codex)
        for path in paths:
            typer.echo(f"  ✓ parsed {Path(path).name}")
        stats = result["stats"]
        typer.echo(typer.style(
            f"✔ Imported {result['volumes']} volumes (ch. {stats['from_chapter']}–{stats['to_chapter']}) "
            f"into novel {result['novel_id']}.", fg=typer.colors.GREEN, bold=True,
        ))
        if codex:
            typer.echo(typer.style("✔ Codex built.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())


@app.command(name="import-worker")
def import_worker():
    """Runs the durable import worker as a standalone process (parse/OCR/commit jobs from the
    DB queue). Use this to split the worker off the web image; Ctrl-C stops it cleanly."""
    if _standalone_worker is None:
        raise RuntimeError("Acquisition standalone worker was not wired")
    try:
        run_cli(_standalone_worker(typer.echo))
    except KeyboardInterrupt:
        typer.echo("Stopped.")
