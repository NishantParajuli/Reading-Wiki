# CLI reference

> **Source of truth:** `tests/contracts/snapshots/cli.json` + `cli_help.json` (the 14
> commands and every help surface are contract-frozen — semantically normalized, so
> wording/options/order may not drift silently). Run from the repo root:

```bash
uv run python -m novelwiki.cli --help
```

Commands use the project environment through `uv run`; an activated pip-installed
`.venv` can omit that prefix.

Architecture note: `novelwiki/cli.py` is a stable alias; real composition lives in
`novelwiki/bootstrap/cli.py`, and each command is a Typer transport in its module's
`adapters/inbound/cli.py` calling the same application commands the web/worker paths use
([../architecture/composition-root.md §6](../architecture/composition-root.md)). Every
command bootstraps via `platform/cli_runtime.py::run_cli` (schema ensure, pool lifecycle,
clean Ctrl-C).

Run commands through `novelwiki.cli`, which wires the application runtime. The internal
chunking, embedding, extraction, and scraper adapter modules are not standalone command
entry points; direct execution exits with the supported CLI command instead of attempting
unwired work.

## Commands (grouped by capability)

### Ingestion — Acquisition

| Command | What it does |
|---|---|
| `add-novel TITLE START_URL [--adapter K] [--lang L] [--raw] [--offset F] [--codex]` | Creates a novel + its first source and prints both ids. CLI novels are **system-owned** (`SystemPrincipal("cli")`, no owner — intentional, ADR 002); runs the `create_novel_with_source` workflow. |
| `scrape NOVEL_ID [--source ID] [--force] [--max N]` | Scrapes a novel's sources chapter by chapter, resuming where each source left off; stops cleanly at premium/paywalled chapters. |
| `import PATH [--novel ID] [--offset F] [--codex]` | Imports an EPUB or **digital** PDF end-to-end (parse → heuristic segment → commit), mirroring the web import worker but with no interactive review. Scanned PDFs need the OCR cost-confirm gate — use the web UI for those. `--novel/--offset` appends to an existing novel. |
| `import-batch FOLDER [--series] [--codex]` | Bulk-imports every EPUB/digital-PDF under a folder. With `--series`, detected EPUB/PDF volumes sharing a series become one multi-volume novel. |
| `import-series PATH... [--codex]` | Several volumes → one multi-volume novel (one source per volume, offsets computed). |
| `import-worker` | Runs the durable import worker as a **standalone process** (claims parse/OCR/commit jobs from the DB queue). Use to split the worker off the web image; leased claims make it safe alongside the in-process worker. Ctrl-C stops cleanly. |

### Translation

| Command | What it does |
|---|---|
| `translate NOVEL_ID [--from F] [--to T] [--force] [--seed]` | Translates raw chapters in the range into English through the exact same engine + atomic `commit_translation` workflow as the web; grows the glossary as it goes. `--seed` first pulls established names from the codex. |

### Codex pipeline

| Command | What it does |
|---|---|
| `chunk NOVEL_ID [--force] [--from F] [--to T]` | Paragraph/sentence-aware chunking into `chunks`; force upserts stable chunk identities, preserves unchanged embeddings, and refuses changed text with a live extraction checkpoint. |
| `embed NOVEL_ID [--from F] [--to T]` | Batch-embeds all chunks missing vectors. |
| `extract NOVEL_ID [--force] [--from F] [--to T]` | Forward-only v2 extraction; force replaces selected chapters and invalidates downstream state/context/hierarchical memory for chronological rebuild. |
| `rebuild-bm25 NOVEL_ID` | Rebuilds + persists the per-novel BM25 index. |
| `merge NOVEL_ID --keep ID --drop ID` | Merges duplicate entities, preserving the dropped canonical name as a spoiler-safe alias while re-pointing references and clearing caches. |
| `reset-codex NOVEL_ID [--force]` | Deletes derived structured Codex knowledge/caches while preserving chunks/embeddings; refuses during an active build. |

The web UI's codex **Build** button runs `chunk → embed → extract → rebuild-bm25` as one
durable job; the CLI exposes the stages individually. `chunk`, `embed`, and `extract` accept
chapter ranges; `rebuild-bm25` rebuilds the whole novel index.

### Platform

| Command | What it does |
|---|---|
| `reset-db [--force]` | **Destructive.** Drops the 46-table reset list in dependency order and re-applies the schema. Interactive confirmation unless `--force`. (`auth_rate_limits` is intentionally absent from the drop list — ADR 002.) |

## Related module-style entrypoints (not Typer commands)

| Invocation | Purpose |
|---|---|
| `uv run python main.py` / `uv run uvicorn novelwiki.api.app:app` | run the server |
| `uv run python -m novelwiki.db.schema` | apply schema DDL explicitly |
| `uv run python -m novelwiki.db.migrate_multiuser` | run the guarded multi-user migration supervised (take a `pg_dump` first) |
| `uv run python -m novelwiki.agy.worker` | the dedicated AGY host worker (normally via systemd — see [../agy-operator-runbook.md](../agy-operator-runbook.md)) |
| `uv run python -m novelwiki.openai_codex.worker` | the dedicated ChatGPT Codex App Server worker (normally via systemd — see [../openai-codex-operator-runbook.md](../openai-codex-operator-runbook.md)) |
| `uv run python try_adapter.py ADAPTER URL [--max N] [--archive-password-env NAME]` | bounded live website diagnostic; prints chapter metadata, creates no jobs and saves no chapter text. Default maximum 2; [details](../pipelines/supported-sites.md#check-a-source-without-importing-it). |

## Typical sequences

Use the novel ID printed by each `add-novel`; the IDs `1` and `2` below are examples,
not a promise about an existing database. Replace example source URLs with
[supported novel or chapter URLs](../pipelines/supported-sites.md). CLI-created novels
are system-owned and editable by admins. `--lang` and `--raw` are explicit source settings;
the CLI does not apply the selected adapter's language default. Encrypted RAW archive
sources require `config.archive_password`, which the `add-novel` CLI does not expose;
create those sources through the web form or HTTP API.

```bash
# Scrape-based novel with codex
uv run python -m novelwiki.cli add-novel "Example" "https://fenrirealm.com/series/example/1" --adapter fenrirealm --codex
uv run python -m novelwiki.cli scrape 1 --max 50
uv run python -m novelwiki.cli chunk 1 && uv run python -m novelwiki.cli embed 1
uv run python -m novelwiki.cli extract 1 && uv run python -m novelwiki.cli rebuild-bm25 1

# Raw novel: scrape + translate the first 20 chapters
uv run python -m novelwiki.cli add-novel "Raw Example" "https://…" --adapter 69shuba --raw --lang zh
uv run python -m novelwiki.cli scrape 2 --max 20
uv run python -m novelwiki.cli translate 2 --from 1 --to 20 --seed

# Calibre library, grouped by series
uv run python -m novelwiki.cli import-batch ~/Calibre --series
```
