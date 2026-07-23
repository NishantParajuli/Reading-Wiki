# CLI reference

> **Source of truth:** `tests/contracts/snapshots/cli.json` + `cli_help.json` (the 14
> commands and every help surface are contract-frozen — semantically normalized, so
> wording/options/order may not drift silently). Run from the repo root:

```bash
python -m novelwiki.cli --help
```

Architecture note: `novelwiki/cli.py` is a stable 9-line alias; real composition lives in
`novelwiki/bootstrap/cli.py`, and each command is a Typer transport in its module's
`adapters/inbound/cli.py` calling the same application commands the web/worker paths use
([../architecture/composition-root.md §6](../architecture/composition-root.md)). Every
command bootstraps via `platform/cli_runtime.py::run_cli` (schema ensure, pool lifecycle,
clean Ctrl-C).

## Commands (baseline order)

### Ingestion — Acquisition

| Command | What it does |
|---|---|
| `add-novel TITLE START_URL [--adapter K] [--language L] [--raw] [--chapter-offset F] [--codex]` | Creates a novel + its first source and prints both ids. CLI novels are **system-owned** (`SystemPrincipal("cli")`, no owner — intentional, ADR 002); runs the `create_novel_with_source` workflow. |
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
| `merge NOVEL_ID --keep ID --drop ID` | Merges duplicate entities (re-points facts/relations/aliases, clears caches). |
| `reset-codex NOVEL_ID [--force]` | Deletes derived structured Codex knowledge/caches while preserving chunks/embeddings; refuses during an active build. |

The web UI's codex **Build** button runs `chunk → embed → extract → rebuild-bm25` as one
durable job; the CLI exposes the stages individually (all idempotent, all range-limitable).

### Platform

| Command | What it does |
|---|---|
| `reset-db [--force]` | **Destructive.** Drops all tables in dependency order and re-applies the schema. Interactive confirmation unless `--force`. (Quirk preserved by contract: `auth_rate_limits` is not in the drop list — ADR 002.) |

## Related module-style entrypoints (not Typer commands)

| Invocation | Purpose |
|---|---|
| `python main.py` / `uvicorn novelwiki.api.app:app` | run the server |
| `python -m novelwiki.db.schema` | apply schema DDL explicitly |
| `python -m novelwiki.db.migrate_multiuser` | run the guarded multi-user migration supervised (take a `pg_dump` first) |
| `python -m novelwiki.agy.worker` | the dedicated AGY host worker (normally via systemd — see [../agy-operator-runbook.md](../agy-operator-runbook.md)) |

## Typical sequences

```bash
# Scrape-based novel with codex
python -m novelwiki.cli add-novel "Example" "https://fenrirealm.com/novel/example/chapter-1" --adapter fenrirealm --codex
python -m novelwiki.cli scrape 1 --max 50
python -m novelwiki.cli chunk 1 && python -m novelwiki.cli embed 1
python -m novelwiki.cli extract 1 && python -m novelwiki.cli rebuild-bm25 1

# Raw novel: scrape + translate the first 20 chapters
python -m novelwiki.cli add-novel "Raw Example" "https://…" --adapter 69shuba --raw --language zh
python -m novelwiki.cli scrape 2 --max 20
python -m novelwiki.cli translate 2 --from 1 --to 20 --seed

# Calibre library, grouped by series
python -m novelwiki.cli import-batch ~/Calibre --series
```
