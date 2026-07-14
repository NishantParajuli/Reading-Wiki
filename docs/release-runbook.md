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

For ordinary merged changes, the local deploy agent performs steps 4-5 automatically after the
GitHub `quality` workflow succeeds for the current `main` SHA. It retains the previous web image as
`wiki-web:rollback`, replaces only the `web` service, checks the loopback `/health` endpoint, and
restores the rollback image on failure. Database backup/restore rehearsal and operator-level smoke
checks remain manual release responsibilities for schema or high-risk changes.

The architecture migration changes code ownership but deliberately retains the existing monolith,
schema, routes, job states, filesystem/cache identities, and deployment topology.
