import asyncio

import typer

from novelwiki.platform.cli_runtime import run_cli
from novelwiki.modules.translation.adapters.outbound.runtime import translate_range, seed_glossary_from_entities

app = typer.Typer()

@app.command()
def translate(
    novel_id: int = typer.Argument(..., help="The novel id"),
    from_chapter: float = typer.Option(None, "--from", help="Only translate chapters >= this number"),
    to_chapter: float = typer.Option(None, "--to", help="Only translate chapters <= this number"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-translate even if already translated"),
    seed: bool = typer.Option(False, "--seed", help="Seed the glossary from codex entities first"),
):
    """Translates raw (foreign-language) chapters into English, growing the name glossary."""
    async def run():
        if seed:
            n = await seed_glossary_from_entities(novel_id)
            typer.echo(f"Seeded {n} glossary terms from codex entities.")
        typer.echo("Translating raw chapters (on-demand glossary-consistent)...")
        count = await translate_range(novel_id, from_chapter=from_chapter, to_chapter=to_chapter, force=force)
        typer.echo(typer.style(f"✔ Translated {count} chapters.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())



