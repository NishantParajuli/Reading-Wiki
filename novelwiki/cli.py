import typer
import asyncio
import json
import logging
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.scraper.runner import scrape_novel, scrape_source
from novelwiki.ingest.chunk import chunk_all_chapters
from novelwiki.ingest.embed import embed_missing_chunks
from novelwiki.ingest.extract import extract_all_chapters
from novelwiki.retrieval.bm25 import get_bm25_manager
from novelwiki.ingest.link import merge_entities

# Mute noisy standard logging for cleaner CLI prints
logging.getLogger("httpx").setLevel(logging.WARNING)

app = typer.Typer(
    help="CLI management engine for the novel reading platform.",
    no_args_is_help=True
)


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
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                novel_id = await conn.fetchval(
                    """
                    INSERT INTO novels (title, codex_enabled, original_language)
                    VALUES ($1, $2, $3) RETURNING id;
                    """,
                    title, codex, language,
                )
                source_id = await conn.fetchval(
                    """
                    INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw, chapter_offset)
                    VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id;
                    """,
                    novel_id, adapter, start_url, json.dumps({}), language, is_raw, chapter_offset,
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
            count = await scrape_source(source_id, force=force, max_chapters=max_chapters)
        else:
            typer.echo(f"Scraping all sources of novel {novel_id}...")
            count = await scrape_novel(novel_id, force=force, max_chapters=max_chapters)
        typer.echo(typer.style(f"✔ Successfully scraped {count} chapters.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
    asyncio.run(run())


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
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await merge_entities(novel_id, keep_id, drop_id, conn)
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
        from novelwiki.db.schema import ALL_TABLES
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                typer.echo("Dropping and clearing all tables...")
                for table in ALL_TABLES:
                    await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
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
