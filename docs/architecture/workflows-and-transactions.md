# Workflows, the kernel, and cross-module transactions

> **Audience:** anyone touching an operation that writes to more than one module's tables,
> or wondering what `uow.transaction.bind(SomethingTransactionApi)` means.

## 1. The problem

Every table has exactly one writer module. But real product operations often need to
mutate several owners **atomically** — committing a translation must update the chapter
(Reading), record newly discovered glossary terms (Translation), and meter the durable
job's quota consumption (Work), and either all of it happens or none of it does. Letting
modules import each other's repositories would destroy the ownership model; giving every
module raw access to a shared connection would smuggle persistence details across every
boundary.

## 2. The kernel contracts (`novelwiki/kernel/`)

The kernel is the shared vocabulary — 3 small files, importable by everyone, importing
nothing:

- **`kernel/transactions.py`** defines two protocols:

  ```python
  class TransactionContext(Protocol):
      """Marker protocol; deliberately exposes no database connection."""
      def bind(self, capability: type[T]) -> T: ...

  class UnitOfWork(Protocol):
      transaction: TransactionContext
      async def __aenter__(self) -> Self: ...
      async def __aexit__(...) -> bool | None: ...
  ```

  The crucial design point: a workflow can *bind* a module's transaction capability to the
  ongoing transaction, but can never get at the connection itself. No participant can
  commit, roll back, or run arbitrary SQL — atomicity is decided in exactly one place.

- **`kernel/errors.py`** — the transport-neutral error family used across all layers:
  `ApplicationError` → `NotFound`, `Forbidden`, `Conflict` (→ `JobAlreadyActive`),
  `ValidationFailed`, `InvalidOperation`, `QuotaExceeded`, `ProviderUnavailable`,
  `RateLimited(detail, retry_after=…)`.

## 3. The Platform implementation (`platform/database/uow.py`)

`AsyncpgUnitOfWork` implements the kernel contract: on `__aenter__` it acquires one pool
connection and opens one `connection.transaction()`; on `__aexit__` it commits (or rolls
back on exception) and releases the connection. Its `transaction` attribute is a
`TransactionBindings` object constructed with a **factory map**:

```python
factories = {
    CatalogTransactionApi:      lambda conn: CatalogTransactionService(PostgresCatalogRepository(conn)),
    AcquisitionTransactionApi:  PostgresAcquisitionTransactionService,
    ReadingTranslationTransactionApi: PostgresReadingTranslationTransactionService,
    ...
}
uow_factory = lambda: AsyncpgUnitOfWork(pool, factories)
```

`bind(SomeTransactionApi)` looks the protocol up in the map, constructs the
connection-bound service on first use, and memoizes it for the rest of the transaction.
Binding an unregistered capability raises `LookupError` immediately — wiring mistakes fail
loudly, not with silent autocommit. Bootstrap owns every factory map (different workflows
register different participant sets).

## 4. The eight named workflows (`novelwiki/workflows/`)

Workflows are the only cross-module *write* coordinators. They are deliberately tiny,
SQL-free, and named after the business operation. The package docstring is the rule:
*"Named cross-module workflows. Workflows own no persistence."*

| Workflow | Participants (transaction-bound) | What it guarantees |
|---|---|---|
| `create_novel_with_source` | Catalog, Acquisition | The novel row, the owner's library entry, and the first source are created together (or not at all). CLI passes `SystemPrincipal("cli")` → ownerless system novel (intentional, ADR 002). |
| `delete_novel` | Catalog, Acquisition | Permission check (`require_editable`), collect the import-job ids for post-commit file cleanup, delete the Catalog root (DB cascades take dependent rows) — one transaction. File/BM25 cleanup happens after commit via `AcquisitionCleanupApi` (known product debt: ADR 002 notes audio/BM25 leftovers are tracked separately). |
| `update_source_offset` | Acquisition, Reading, Codex | Renumbering a source's chapters onto new global numbers is all-or-nothing, and is **refused** (`ValueError`) if Codex has *any* chapter-keyed artifact built on the old numbering — the guard checks every artifact type, not just chunks (an ADR 002 fix-first item). |
| `commit_import` | Acquisition, Catalog, Reading, Codex | An import commit (create/append novel, create source, upsert chapters, register assets, invalidate codex ranges, finalize the import job) runs as one prepared operation over an `ImportCommitApis` bundle of the four owners. |
| `commit_translation` | Reading, Translation, Work | Chapter content+version update, discovered glossary terms, and `quota_consumed += 1` land atomically. Reading's commit is optimistic-concurrency-checked (`expected_source_hash`, `expected_content_version`) and returns `{"idempotent": True}` when this exact translation already landed — in which case the workflow *skips* the term insert and metering (no double-charge). |
| `commit_codex_extraction` | Reading, Codex | Re-reads the chapter **with a row lock inside the transaction** (`locked_chapter_snapshot`), recomputes its SHA-256, and aborts with `source_changed` if the text no longer matches what the model actually read — then commits all Codex artifacts for the chapter. This closes the race where a re-scrape/edit lands mid-extraction. |
| `finalize_job_quota` | Work, Identity | Settling a terminal job (compute refundable units, mark `quota_finalized`) and refunding the user's quota happen in one transaction; the `quota_finalized` guard makes settlement exactly-once. Fixes the baseline "refund crash window" defect (ADR 002). |
| `schedule_ai_job` | requesting feature, Identity quota, Work | *Not* UoW-based — a **guarded compensation** shape: `reserve() → [before_schedule()] → schedule() → refund on exception or on dedupe (created=False)`. Initial AI scheduling intentionally stays compensating rather than atomic; the reasoning and the known process-crash window are recorded in [ADR 003](adr-003-ai-scheduling-consistency.md). |

### Reading one to internalize the pattern

```python
# novelwiki/workflows/commit_translation.py (abridged)
async def commit_translation(uow_factory, novel_id, chapter, *, expected_source_hash,
                             expected_content_version, translated_title, translation,
                             new_terms, model_label, run_id=None, job_id=None) -> dict:
    async with uow_factory() as uow:
        reading = uow.transaction.bind(ReadingTranslationTransactionApi)
        result = await reading.commit_translation(...)
        if result.get("idempotent"):
            return result
        translation_api = uow.transaction.bind(TranslationTransactionApi)
        await translation_api.insert_discovered_terms(novel_id, new_terms)
        if job_id is not None:
            work = uow.transaction.bind(WorkTransactionApi)
            await work.increment_quota_consumed(job_id, 1)
    return {**result, "new_terms": len(new_terms)}
```

Note everything that is *absent*: no SQL, no connection, no commit/rollback, no imports of
module internals — only public transaction capabilities and control flow.

## 5. Rules for writing a new workflow

1. It must be a **named business operation** — if you can't name it, it's probably two
   operations.
2. Only bind `…TransactionApi` protocols from `public.py` files. If a participant lacks
   one, add it (plus a connection-bound `…TransactionService` in that module's outbound
   layer, registered in Bootstrap's factory map).
3. No branching business policy inside the workflow — policy belongs in the participants;
   the workflow sequences them.
4. Raise kernel errors (or let participants' errors propagate); the enclosing adapter
   translates.
5. Keep post-commit side effects (file deletion, cache invalidation on disk) *out* of the
   transaction — return what's needed and let the caller run cleanup afterwards, as
   `delete_novel` does.
6. Update [module-ownership.md](module-ownership.md)'s workflow table.

## 6. Single-module transactions

A write that stays within one module does **not** need a workflow. Module repositories
manage their own transactionality (single statements, or a `connection.transaction()`
inside one repository method). The UoW machinery exists specifically for *multi-owner*
atomicity; using it for everything would just add ceremony.
