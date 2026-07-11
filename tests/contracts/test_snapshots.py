from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_contract_snapshots_match_runtime():
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, str(root / "scripts/contracts.py")],
        cwd=root,
        check=True,
    )


def test_contract_snapshots_ignore_terminal_width():
    root = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "COLUMNS": "137",
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
    }
    subprocess.run(
        [sys.executable, str(root / "scripts/contracts.py")],
        cwd=root,
        env=environment,
        check=True,
    )


def test_agy_contract_snapshot_contains_source_assets_only():
    root = Path(__file__).resolve().parents[2]
    snapshot = json.loads(
        (root / "tests/contracts/snapshots/agy_contracts.json").read_text(
            encoding="utf-8"
        )
    )
    paths = snapshot["plugin_files"]
    assert paths
    assert not any("__pycache__" in path for path in paths)
    assert not any(path.endswith((".pyc", ".pyo")) for path in paths)


def test_cli_help_normalization_discards_layout_not_content():
    from scripts.contracts import _normalize_cli_help

    wide = "╭────╮\n│ --force  Force existing chapters │\n╰────╯"
    narrow = "\x1b[1m╭──╮\x1b[0m\n│ --force │\n│ Force existing │\n│ chapters │\n╰──╯"
    assert _normalize_cli_help(wide) == _normalize_cli_help(narrow)
    assert _normalize_cli_help(wide) == "--force Force existing chapters"
