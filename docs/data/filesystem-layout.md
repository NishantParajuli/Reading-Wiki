# Filesystem layout

The database holds state and pointers; heavy bytes live on disk. Every filesystem root
has **one owner module** (same rule as tables). In Docker, everything under `./data` is
the named volume `novelwiki_data` mounted at `/app/data` — it must persist across image
rebuilds.

```
./data/                          (volume root; settings paths below are relative defaults)
├── bm25_index/<novel_id>/       Codex — persisted bm25s lexical index per novel
├── assets/                      Acquisition (+ Identity for _users)
│   ├── <novel_id>/              extracted images: covers, illustrations, page scans
│   │                            (content-addressed names from assets.sha256)
│   └── _users/<user_id>/        avatars — the ONLY publicly mounted assets
│                                (served at /assets/_users; everything else goes through
│                                access-controlled /api/assets/... routes)
├── audio/                       Narration — cached Opus narration files
│   └── <novel-scoped paths from chapter_audio.audio_path>
│                                deliberately OUTSIDE assets/ so private-novel audio is
│                                only reachable via the permission-checked audio route
└── imports/                     Acquisition — import pipeline artifacts
    ├── incoming/                watched drop folder (IMPORT_INCOMING_DIR) for big files;
    │                            POST /api/import/scan-incoming picks them up
    └── <job-scoped dirs>        original blobs, parsed block-stream IR, chunked-upload
                                 scratch (partial files during resumable uploads)
```

Outside the repo/volume:

```
~/.local/share/novelwiki/agy-jobs/     AI Execution — AGY run workspaces (AGY_WORK_DIR)
└── <job_id>/
    ├── <run_id>/                      input/ plus `.agents`/`.git` customizations
    │                                  (sealed read-only), writable output/ and logs/;
    │                                  size-capped and hash-verified.
    └── .<run_id>.agy-state/           isolated mutable AGY CLI state and run-only
                                       settings; links only the validated CLI-owned
                                       credential files and is never agent-readable.
```

Both directories are swept together after `AGY_SUCCESS/FAILURE_RETENTION_HOURS`. They stay
outside the checkout and public asset roots because the workspace and CLI transcript state
can contain story text.

Sidecar-adjacent:

```
sidecar-tts/voices/              narrator reference clips (voice cloning prompts);
                                 mounted read-only into the TTS container — add/replace
                                 a clip + restart, no image rebuild (see its README)
```

## Settings that control these paths

| Setting | Default | Meaning |
|---|---|---|
| `BM25_INDEX_PATH` | `./data/bm25_index` | per-novel lexical indexes |
| `ASSET_DIR` | `./data/assets` | images + avatars root |
| `AUDIO_DIR` | `./data/audio` | narration cache root |
| `IMPORT_DIR` | `./data/imports` | import job artifacts |
| `IMPORT_INCOMING_DIR` | `./data/imports/incoming` | watched drop folder |
| `AGY_WORK_DIR` | `~/.local/share/novelwiki/agy-jobs` | AGY workspaces |

## Serving rules (why two asset paths exist)

- **Public static:** only `/assets/_users` (avatars) and the built SPA
  (`novelwiki/frontend/dist`, hashed bundles cached immutable) are mounted publicly
  (`platform/web/static.py`).
- **Access-controlled:** novel images stream through
  `GET /api/assets/novels/{novel_id}/{filename}` (Catalog readable-check) and import
  previews through `GET /api/assets/import-jobs/{job_id}/{filename}` (job ownership);
  narration through `GET …/audio.opus` (readable-check + Range support). Experience
  projections rewrite any historical public URL onto these routes.

## Lifecycle & cleanup

- **BM25 indexes** rebuild from the DB at any time (`rebuild-bm25`); staleness is
  detected via a cheap DB signature, so deleting an index directory is always safe.
- **Import scratch** is job-scoped; abandoned `receiving` upload sessions are GC'd after
  `IMPORT_UPLOAD_SESSION_TTL_HOURS` (24) by the import worker's maintenance sweep.
- **Novel deletion** cleans import-job artifacts via `AcquisitionCleanupApi` post-commit.
  Known debt (ADR 002): orphaned audio files and BM25 directories of a deleted novel are
  tracked as a separate storage change — harmless leftovers, recreated-from-DB semantics.
- **AGY workspaces and their sibling CLI state directories** are retention-swept by the
  host worker (24 h success / 168 h failure).

## Backup guidance

`pg_dump` covers all state; of the filesystem, only `data/assets`, `data/audio`, and
original files under `data/imports` are not derivable (indexes and scratch are).
The rehearsed procedure is `scripts/rehearse-backup-restore.sh` +
[../release-runbook.md](../release-runbook.md).
