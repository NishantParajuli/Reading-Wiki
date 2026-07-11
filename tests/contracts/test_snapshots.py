from __future__ import annotations

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
