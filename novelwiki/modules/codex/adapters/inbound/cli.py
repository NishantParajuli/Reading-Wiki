import typer

from novelwiki.platform.cli_runtime import run_cli

app = typer.Typer()

_command_factory = None


def configure_commands(factory) -> None:
    global _command_factory
    _command_factory = factory

def _commands():
    if _command_factory is None:
        raise RuntimeError("Codex CLI commands were not wired by the composition root")
    return _command_factory()

@app.command()
def chunk(
    novel_id: int = typer.Argument(..., help="The novel id"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-chunking even if chunks exist"),
    from_chapter: float = typer.Option(None, "--from", help="Only chunk chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only chunk chapters <= this number"),
):
    """Splits readable chapter text into overlapping, within-chapter passage chunks."""
    async def run():
        typer.echo("Running within-chapter text chunker...")
        count = await _commands().chunk(novel_id, force=force, start=from_chapter, end=to_chapter)
        typer.echo(typer.style(f"✔ Successfully generated {count} overlapping chunks.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())


@app.command()
def embed(
    novel_id: int = typer.Argument(..., help="The novel id"),
    from_chapter: float = typer.Option(None, "--from", help="Only embed chunks in chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only embed chunks in chapters <= this number"),
):
    """Generates vector embeddings for any chunks missing them."""
    async def run():
        typer.echo("Running vector embedding pipeline...")
        count = await _commands().embed(novel_id, start=from_chapter, end=to_chapter)
        typer.echo(typer.style(f"✔ Successfully embedded {count} chunks.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())


@app.command()
def extract(
    novel_id: int = typer.Argument(..., help="The novel id"),
    force: bool = typer.Option(False, "--force", "-f", help="Force re-extraction of chapters"),
    from_chapter: float = typer.Option(None, "--from", help="Only extract chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only extract chapters <= this number (e.g. iterate on the first 50)"),
):
    """Performs forward-only structured entity/fact extraction in chronological order."""
    async def run():
        typer.echo("Launching forward-only structured knowledge extraction pass (Flash)...")
        await _commands().extract(novel_id, force=force, start=from_chapter, end=to_chapter)
        typer.echo(typer.style("✔ Extraction and entity-resolution completed.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())


@app.command()
def rebuild_bm25(
    novel_id: int = typer.Argument(..., help="The novel id"),
):
    """Rebuilds and persists the per-novel sparse BM25 lexical search index."""
    async def run():
        typer.echo("Building and persisting in-process BM25 lexical search index...")
        await _commands().rebuild(novel_id)
        typer.echo(typer.style("✔ BM25 index rebuilt and persisted.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())


@app.command()
def merge(
    novel_id: int = typer.Argument(..., help="The novel id"),
    keep_id: int = typer.Option(..., "--keep", "-k", help="The entities.id of the entity to KEEP"),
    drop_id: int = typer.Option(..., "--drop", "-d", help="The entities.id of the duplicate entity to MERGE and DELETE")
):
    """Deduplicates and merges two duplicate entities in the database."""
    async def run():
        await _commands().merge(novel_id, keep_id, drop_id)
        typer.echo(typer.style(f"✔ Entity {drop_id} successfully merged into {keep_id}.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())

