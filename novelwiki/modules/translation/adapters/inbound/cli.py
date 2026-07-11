import typer

from novelwiki.platform.cli_runtime import run_cli

app = typer.Typer()

_command_factory = None


def configure_commands(factory) -> None:
    global _command_factory
    _command_factory = factory

def _commands():
    if _command_factory is None:
        raise RuntimeError("Translation CLI commands were not wired by the composition root")
    return _command_factory()

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
        seeded, count = await _commands().translate(
            novel_id, start=from_chapter, end=to_chapter, force=force, seed=seed
        )
        if seed:
            n = seeded
            typer.echo(f"Seeded {n} glossary terms from codex entities.")
        typer.echo("Translating raw chapters (on-demand glossary-consistent)...")
        typer.echo(typer.style(f"✔ Translated {count} chapters.", fg=typer.colors.GREEN, bold=True))
    run_cli(run())

