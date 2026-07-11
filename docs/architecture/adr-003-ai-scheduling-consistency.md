# ADR 003: AI scheduling uses guarded compensation

Status: Accepted for migration compatibility

AI job scheduling preserves the established sequence: validate and resolve the
backend, reserve quota, perform any owner command, create or deduplicate the durable
job, and refund the speculative reservation on failure or deduplication.

Job/quota *finalization* is transaction-bound and atomic. Initial scheduling remains
a compensating workflow because backend-policy resolution and the existing job
creation path include concurrency reauthorization and post-commit audit behavior that
are intentionally outside a shared owner transaction. Converting only the two writes
would change the ordering and failure surface of that contract.

The known limitation is a process-crash window after reservation and before durable
job creation/refund. Ordinary exceptions and deduplication races are compensated and
covered by tests. Eliminating the crash window requires an outbox/reservation-reaper
product change and is not represented as atomic in migration completion claims.
