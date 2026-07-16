import logging

import typer

from novelwiki.platform.observability.logging import configure_logging

configure_logging()

from novelwiki.modules.acquisition.adapters.inbound.cli import (
    app as acquisition_cli,
    configure_cli as configure_acquisition_cli,
)
from novelwiki.modules.codex.adapters.inbound.cli import (
    app as codex_cli,
    configure_commands as configure_codex_commands,
)
from novelwiki.modules.translation.adapters.inbound.cli import (
    app as translation_cli,
    configure_commands as configure_translation_commands,
)
from novelwiki.platform.cli import app as platform_cli
from novelwiki.bootstrap.feature_cli import (
    build_codex_commands,
    build_translation_commands,
)
from novelwiki.bootstrap.acquisition_cli import (
    build_acquisition_commands,
    run_standalone_import_worker,
)

configure_acquisition_cli(build_acquisition_commands, run_standalone_import_worker)
configure_codex_commands(build_codex_commands)
configure_translation_commands(build_translation_commands)

logging.getLogger("httpx").setLevel(logging.WARNING)

app = typer.Typer(
    help="CLI management engine for the novel reading platform.",
    no_args_is_help=True,
)
commands = [
    command
    for feature_cli in (acquisition_cli, codex_cli, translation_cli, platform_cli)
    for command in feature_cli.registered_commands
]
by_name = {
    command.name or command.callback.__name__.replace("_", "-"): command
    for command in commands
}
baseline_order = (
    "add-novel", "scrape", "chunk", "embed", "extract", "translate",
    "import", "import-batch", "import-series", "import-worker",
    "rebuild-bm25", "merge", "reset-codex", "reset-db",
)
app.registered_commands.extend(by_name[name] for name in baseline_order)
