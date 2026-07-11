#!/usr/bin/env python3
"""Update or verify architecture-migration contract snapshots."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SNAPSHOTS = ROOT / "tests" / "contracts" / "snapshots"


def _json(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _contracts() -> dict[str, str]:
    from novelwiki.api.app import app
    from novelwiki.cli import app as cli_app
    from novelwiki.db.schema import ALL_TABLES, DDL_QUERIES
    from novelwiki.importer.jobs import _MARKER_RESUME as IMPORT_MARKER_RESUME
    from novelwiki.importer.jobs import TRIGGER_STATUSES as IMPORT_TRIGGER_STATUSES
    from novelwiki.jobs.service import ACTIVE_STATUSES, KINDS, TERMINAL_STATUSES, TRIGGER_STATUSES
    from novelwiki.tts.worker import ACTIVE_STATUSES as TTS_ACTIVE_STATUSES

    openapi = app.openapi()
    routes = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"})
        for method in methods:
            routes.append(
                {
                    "method": method,
                    "path": route.path,
                    "name": route.name,
                }
            )
    routes.sort(key=lambda item: (item["path"], item["method"], item["name"]))

    commands = sorted(
        command.name or command.callback.__name__.replace("_", "-")
        for command in cli_app.registered_commands
    )
    normalized_ddl = [re.sub(r"\s+", " ", query).strip() for query in DDL_QUERIES]
    states = {
        "generic": {
            "kinds": list(KINDS),
            "trigger": list(TRIGGER_STATUSES),
            "active": list(ACTIVE_STATUSES),
            "terminal": list(TERMINAL_STATUSES),
        },
        "import": {
            "trigger": list(IMPORT_TRIGGER_STATUSES),
            "marker_resume": [
                {"markers": list(markers), "resume": resume}
                for markers, resume in IMPORT_MARKER_RESUME
            ],
        },
        "tts": {"active": sorted(TTS_ACTIVE_STATUSES)},
    }
    return {
        "openapi.json": _json(openapi),
        "routes.json": _json(routes),
        "cli.json": _json(commands),
        "schema.json": _json({"all_tables": list(ALL_TABLES), "ddl": normalized_ddl}),
        "job_states.json": _json(states),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    contracts = _contracts()
    failures = []
    for name, content in contracts.items():
        path = SNAPSHOTS / name
        if args.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        elif not path.exists() or path.read_text(encoding="utf-8") != content:
            failures.append(name)
    if failures:
        print("Contract snapshots differ: " + ", ".join(failures), file=sys.stderr)
        print("Review the change, then run: uv run python scripts/contracts.py --update", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
