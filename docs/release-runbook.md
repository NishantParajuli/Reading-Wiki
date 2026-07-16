# Release and rollback runbook

1. Run the complete CI/release-candidate gates documented in `docs/testing.md`.
2. Run `scripts/rehearse-backup-restore.sh` against the production PostgreSQL version using the
   disposable rehearsal database names. Preserve its successful log with the release artifact.
3. Create a production `pg_dump --format=custom --no-owner` backup, record its checksum, and verify
   `pg_restore --list` before changing the application image.
4. Record the current image digest and keep it available as the rollback image. Build the candidate
   from the exact tested commit and record its digest.
5. Deploy the candidate without changing external topology. Confirm `/health`, login/CSRF, Library,
   Reader, one provider-free cached Codex read, and worker heartbeat visibility.
6. Observe request errors, auth failures, queued/running/waiting-provider counts, stale leases,
   sidecar errors, and provider/quota spend. Do not retry expensive jobs in bulk until the queue is
   understood. Use the structured event fields and baseline queries in
   [operations/logging.md](operations/logging.md); confirm `worker.started` exists for every
   enabled role and investigate `worker.loop_failed` or heartbeat failures first.
7. For an application-only regression, restore the prior image. For a data/schema regression, stop
   writers, restore the verified database backup into a new database, point the prior image at it,
   and validate counts/health before reopening traffic. Do not use destructive down migrations as
   rollback.

## First Codex v2 production rollout

Use this controlled path once for any production novel that already has v1 Codex data.
It applies to both API and AGY builds; backend choice does not change the schema, context,
or commit contract.

1. Enter a Codex maintenance window. Set `AGY_CODEX_ENABLED=false`, stop the AGY host
   worker if it is running, prevent new Build requests, and let active `codex_build` jobs
   finish or request cancellation through `POST /api/jobs/{job_id}/cancel`. Do not reset
   while any Codex job remains active.
2. Complete the backup and candidate-image steps above. Apply the candidate's additive
   schema before allowing either worker path to run:

   ```bash
   docker compose run --rm --no-deps web python -m novelwiki.db.schema
   ```

   Startup applies the same idempotent DDL, but this explicit step makes schema failure a
   deployment gate rather than discovering it after workers start.
3. Choose one data path per novel:

   - **Chronological in-place migration:** retain v1 rows and existing narrative
     chunks/embeddings. The first v2 Build must begin at the novel's first narrative
     chapter; a middle-of-book start fails closed until all preceding v2 chapter summaries
     and checkpoints exist.
   - **Clean structured rebuild:** recommended when legacy extraction touched front/back
     matter or when a clean comparison is preferred. Using the candidate image, run
     `python -m novelwiki.cli reset-codex NOVEL_ID --force`. This deletes structured
     knowledge and caches but preserves chunks/embeddings. Then Build from the first
     narrative chapter.

4. Start the candidate web service. Canary the earliest chapter first, then extend only in
   chronological ranges. Before a whole-book continuation, verify pipeline version `2.0`,
   source/context hashes, provenance, literal mention spans, context token/entity counts,
   and the first 25-chapter checkpoint. Where real `part_label` values exist, verify a
   volume summary only after that labeled volume's final narrative chapter. Do not jump
   directly to a late/checkpoint/volume chapter without its v2 prerequisites.
5. Keep `AGY_CODEX_ENABLED=false` until the pinned plugin passes representative early,
   late, checkpoint-end, and final-volume canaries. API can remain the controlled fallback;
   both backends ultimately use the same atomic commit workflow.

The eight v2 tables and two `extraction_state` columns are additive, so the previous image
can run after schema creation **only if no reset or v2 extraction has changed Codex data**.
Once a clean reset or any v2 chapter commit has occurred, do not treat an image-only rollback
as data-safe: restore the pre-rollout database backup with the previous image. Never drop the
additive tables as an ad-hoc rollback.

For ordinary merged changes, the local deploy agent performs steps 4-5 automatically after the
GitHub `quality` workflow succeeds for the current `main` SHA. It retains the previous web image as
`wiki-web:rollback`, replaces only the `web` service, checks the loopback `/health` endpoint, and
restores the rollback image on failure. Database backup/restore rehearsal and operator-level smoke
checks remain manual release responsibilities for schema or high-risk changes.

The earlier architecture migration changed code ownership while retaining the monolith and
deployment topology. Feature releases may still add schema or data contracts; follow any
feature-specific rollout section above rather than assuming an image-only rollback is safe.
