#!/usr/bin/env python3
"""Run backend tests against a disposable database without exposing DSNs."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _host_accessible_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname != "host.docker.internal":
        return url
    host = "127.0.0.1"
    if parsed.port:
        host += f":{parsed.port}"
    if parsed.username:
        credentials = parsed.username
        if parsed.password:
            credentials += f":{parsed.password}"
        host = f"{credentials}@{host}"
    return urlunparse(parsed._replace(netloc=host))


def main() -> int:
    missing = [
        name for name in ("TEST_DATABASE_URL", "TEST_DB_SUPERUSER_URL")
        if not os.environ.get(name)
    ]
    if missing:
        print(
            "Refusing to derive destructive-test authority from application settings; "
            "set " + " and ".join(missing) + " to disposable test-only PostgreSQL URLs.",
            file=sys.stderr,
        )
        return 2
    for name in ("TEST_DATABASE_URL", "TEST_DB_SUPERUSER_URL"):
        os.environ[name] = _host_accessible_url(os.environ[name])
    return pytest.main(sys.argv[1:] or ["-q"])


if __name__ == "__main__":
    raise SystemExit(main())
