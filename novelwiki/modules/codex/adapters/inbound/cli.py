import asyncio

import typer

from novelwiki.db.connection import close_db_pool
from novelwiki.ingest.chunk import chunk_all_chapters
from novelwiki.ingest.embed import embed_missing_chunks
from novelwiki.ingest.extract import extract_all_chapters
from novelwiki.ingest.link import merge_entities
from novelwiki.retrieval.bm25 import get_bm25_manager

app = typer.Typer()

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
        count = await chunk_all_chapters(novel_id, force=force, from_chapter=from_chapter, to_chapter=to_chapter)
        typer.echo(typer.style(f"✔ Successfully generated {count} overlapping chunks.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def embed(
    novel_id: int = typer.Argument(..., help="The novel id"),
    from_chapter: float = typer.Option(None, "--from", help="Only embed chunks in chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only embed chunks in chapters <= this number"),
):
    """Generates vector embeddings for any chunks missing them."""
    async def run():
        typer.echo("Running vector embedding pipeline...")
        count = await embed_missing_chunks(novel_id, from_chapter=from_chapter, to_chapter=to_chapter)
        typer.echo(typer.style(f"✔ Successfully embedded {count} chunks.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


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
        await extract_all_chapters(novel_id, force=force, from_chapter=from_chapter, to_chapter=to_chapter)
        typer.echo(typer.style("✔ Extraction and entity-resolution completed.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def rebuild_bm25(
    novel_id: int = typer.Argument(..., help="The novel id"),
):
    """Rebuilds and persists the per-novel sparse BM25 lexical search index."""
    async def run():
        typer.echo("Building and persisting in-process BM25 lexical search index...")
        await get_bm25_manager(novel_id).rebuild()
        typer.echo(typer.style("✔ BM25 index rebuilt and persisted.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def merge(
    novel_id: int = typer.Argument(..., help="The novel id"),
    keep_id: int = typer.Option(..., "--keep", "-k", help="The entities.id of the entity to KEEP"),
    drop_id: int = typer.Option(..., "--drop", "-d", help="The entities.id of the duplicate entity to MERGE and DELETE")
):
    """Deduplicates and merges two duplicate entities in the database."""
    async def run():
        from novelwiki.bootstrap.cli_services import merge_codex_entities
        await merge_codex_entities(novel_id, keep_id, drop_id)
        typer.echo(typer.style(f"✔ Entity {drop_id} successfully merged into {keep_id}.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())



