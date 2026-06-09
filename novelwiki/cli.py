import typer
import asyncio
import logging
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.scraper.runner import scrape_novel
from novelwiki.ingest.chunk import chunk_all_chapters
from novelwiki.ingest.embed import embed_missing_chunks
from novelwiki.ingest.extract import extract_all_chapters
from novelwiki.retrieval.bm25 import bm25_manager
from novelwiki.ingest.link import merge_entities

# Mute noisy standard logging for cleaner CLI prints
logging.getLogger("httpx").setLevel(logging.WARNING)

app = typer.Typer(
    help="CLI management engine for the Spoiler-Aware Webnovel Wiki pipeline.",
    no_args_is_help=True
)


@app.command()
def scrape(
    start_url: str = typer.Argument(..., help="The starting chapter page URL"),
    force: bool = typer.Option(False, "--force", "-f", help="Force scrape already existing chapters"),
    max_chapters: int = typer.Option(None, "--max", "-m", help="Maximum number of chapters to scrape in this run")
):
    """Politely scrapes the novel chapter by chapter, following 'Next' pagination links."""
    async def run():
        typer.echo(f"Starting sequential scraper at {start_url}...")
        count = await scrape_novel(start_url, force=force, max_chapters=max_chapters)
        typer.echo(typer.style(f"✔ Successfully scraped {count} chapters.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def chunk(
    force: bool = typer.Option(False, "--force", "-f", help="Force re-chunking even if chunks exist"),
    from_chapter: float = typer.Option(None, "--from", help="Only chunk chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only chunk chapters <= this number"),
):
    """Splits raw scraped chapters into overlapping, within-chapter passage chunks."""
    async def run():
        typer.echo("Running within-chapter text chunker...")
        count = await chunk_all_chapters(force=force, from_chapter=from_chapter, to_chapter=to_chapter)
        typer.echo(typer.style(f"✔ Successfully generated {count} overlapping chunks.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def embed(
    from_chapter: float = typer.Option(None, "--from", help="Only embed chunks in chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only embed chunks in chapters <= this number"),
):
    """Generates vector embeddings for any chunks missing them."""
    async def run():
        typer.echo("Running vector embedding pipeline...")
        count = await embed_missing_chunks(from_chapter=from_chapter, to_chapter=to_chapter)
        typer.echo(typer.style(f"✔ Successfully embedded {count} chunks.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def extract(
    force: bool = typer.Option(False, "--force", "-f", help="Force re-extraction of chapters"),
    from_chapter: float = typer.Option(None, "--from", help="Only extract chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only extract chapters <= this number (e.g. iterate on the first 50)"),
):
    """Performs forward-only structured entity/fact extraction in chronological order."""
    async def run():
        typer.echo("Launching forward-only structured knowledge extraction pass (Flash)...")
        await extract_all_chapters(force=force, from_chapter=from_chapter, to_chapter=to_chapter)
        typer.echo(typer.style("✔ Extraction and entity-resolution completed.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def rebuild_bm25():
    """Rebuilds and persists the local sparse BM25 lexical search index."""
    async def run():
        typer.echo("Building and persisting in-process BM25 lexical search index...")
        await bm25_manager.rebuild()
        typer.echo(typer.style("✔ BM25 index rebuilt and persisted.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def merge(
    keep_id: int = typer.Option(..., "--keep", "-k", help="The entities.id of the entity to KEEP"),
    drop_id: int = typer.Option(..., "--drop", "-d", help="The entities.id of the duplicate entity to MERGE and DELETE")
):
    """Deduplicates and merges two duplicate entities in the database."""
    async def run():
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await merge_entities(keep_id, drop_id, conn)
        typer.echo(typer.style(f"✔ Entity {drop_id} successfully merged into {keep_id}.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


@app.command()
def reset_db(
    force: bool = typer.Option(False, "--force", "-f", help="Force reset without interactive prompt")
):
    """Resets the entire database by dropping all tables, data, and re-applying schema."""
    if not force:
        confirm = typer.confirm("⚠️ Are you sure you want to drop ALL data and reset the database? This cannot be undone.")
        if not confirm:
            typer.echo("Aborted.")
            return
            
    async def run():
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                typer.echo("Dropping and clearing all tables...")
                await conn.execute("DROP TABLE IF EXISTS query_cache CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS wiki_cache CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS extraction_state CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS events CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS relationships CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS entity_facts CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS identity_links CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS entity_aliases CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS entity_descriptions CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS entities CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS chunks CASCADE;")
                await conn.execute("DROP TABLE IF EXISTS chapters CASCADE;")
        typer.echo(typer.style("✔ All tables dropped successfully.", fg=typer.colors.GREEN, bold=True))
        
        # Now re-apply schema DDL
        from novelwiki.db.schema import init_database
        typer.echo("Re-initializing database schema...")
        await init_database()
        typer.echo(typer.style("✔ Database reset and clean schema initialized.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
        
    asyncio.run(run())


if __name__ == "__main__":
    app()
