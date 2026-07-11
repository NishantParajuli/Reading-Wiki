"""Stable Typer entrypoint delegating to CLI composition."""

from novelwiki.bootstrap.cli import app

__all__ = ["app"]


if __name__ == "__main__":
    app()
