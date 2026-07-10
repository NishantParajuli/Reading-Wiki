#!/usr/bin/env python3
"""No-subscription fake for AGY runner chaos tests."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if args == ["--version"]:
        print("1.1.1"); return 0
    if args == ["models"]:
        print("Gemini 3.5 Flash (Medium)\nGemini 3.5 Flash (High)"); return 0
    if args[:2] == ["plugin", "validate"]:
        return 0
    try:
        prompt = args[args.index("--print") + 1]
    except (ValueError, IndexError):
        print("missing --print", file=sys.stderr); return 2
    mode = prompt.split(":", 1)[0]
    output = Path.cwd() / "output"
    output.mkdir(exist_ok=True)
    if mode == "inspect":
        (output / "observed.json").write_text(json.dumps({
            "cwd": str(Path.cwd()), "argv": args, "env_keys": sorted(os.environ),
            "stdin_closed": sys.stdin.read() == "",
        }))
        return 0
    if mode == "nonzero":
        print("server error: temporarily unavailable", file=sys.stderr); return 7
    if mode == "quota":
        print("weekly quota resource exhausted", file=sys.stderr); return 8
    if mode == "flood":
        sys.stdout.write("x" * 2_000_000); sys.stderr.write("y" * 2_000_000); return 0
    if mode == "timeout":
        time.sleep(30); return 0
    if mode == "spawn":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        (output / "child.pid").write_text(str(child.pid))
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(30); return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
