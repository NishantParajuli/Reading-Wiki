import typer

app = typer.Typer()

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
        from novelwiki.bootstrap.cli_services import reset_database
        typer.echo("Dropping and clearing all tables...")
        await reset_database()
        typer.echo(typer.style("✔ All tables dropped successfully.", fg=typer.colors.GREEN, bold=True))
        typer.echo("Re-initializing database schema...")
        typer.echo(typer.style("✔ Database reset and clean schema initialized.", fg=typer.colors.GREEN, bold=True))
        await close_db_pool()
        
    asyncio.run(run())


if __name__ == "__main__":
    app()

