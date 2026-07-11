#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlsplit, urlunsplit

import asyncpg


def database_url(base: str, name: str) -> str:
    parts = urlsplit(base)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


async def run(args) -> None:
    if args.action == "url":
        print(database_url(args.superuser_url, args.database)); return
    if args.action in {"create", "drop"}:
        connection = await asyncpg.connect(args.superuser_url)
        try:
            for name in (args.source, args.restore):
                if not name.startswith("novelwiki_rehearsal_"):
                    raise SystemExit("refusing non-rehearsal database name")
                await connection.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=$1 AND pid<>pg_backend_pid()", name,
                )
                await connection.execute(f'DROP DATABASE IF EXISTS "{name}"')
                if args.action == "create":
                    await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()
        return
    if args.action == "seed":
        connection = await asyncpg.connect(args.database_url)
        try:
            await connection.execute(
                "INSERT INTO novels(title,visibility) VALUES($1,'private')", "Rehearsal marker",
            )
        finally:
            await connection.close()
        return
    source, restored = await asyncpg.connect(args.source_url), await asyncpg.connect(args.restore_url)
    try:
        tables = "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        source_tables = [row[0] for row in await source.fetch(tables)]
        restored_tables = [row[0] for row in await restored.fetch(tables)]
        if source_tables != restored_tables:
            raise SystemExit("restored table catalog differs")
        for table in source_tables:
            left = await source.fetchval(f'SELECT COUNT(*) FROM "{table}"')
            right = await restored.fetchval(f'SELECT COUNT(*) FROM "{table}"')
            if left != right:
                raise SystemExit(f"row-count mismatch for {table}: {left} != {right}")
    finally:
        await source.close(); await restored.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create"); create.add_argument("--superuser-url", required=True); create.add_argument("--source", required=True); create.add_argument("--restore", required=True)
    drop = sub.add_parser("drop"); drop.add_argument("--superuser-url", required=True); drop.add_argument("--source", required=True); drop.add_argument("--restore", required=True)
    url = sub.add_parser("url"); url.add_argument("--superuser-url", required=True); url.add_argument("--database", required=True)
    seed = sub.add_parser("seed"); seed.add_argument("--database-url", required=True)
    verify = sub.add_parser("verify"); verify.add_argument("--source-url", required=True); verify.add_argument("--restore-url", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
