# ADR 001: Modular monolith with Clean Architecture boundaries

- Status: accepted
- Date: 2026-07-11
- Baseline: `c244a1f`

## Decision

NovelWiki remains one FastAPI deployment, one React SPA, and one PostgreSQL database. Business
code is owned by the canonical modules `identity`, `catalog`, `reading`, `acquisition`,
`translation`, `codex`, `narration`, `work`, `ai_execution`, and `experience`.

Within a module, inbound adapters depend on application code, application code depends on domain
rules and ports, and outbound adapters implement those ports. A module may import only stable types
from another module's `public.py`; executable capabilities are injected by the composition root.
Cross-module atomic operations are named, SQL-free workflows using transaction-bound public APIs.

Each database table and filesystem root has one writer owner as defined in
`implementation-plan/modular-monolith-clean-architecture-migration-plan.md`. Experience is the only
business module allowed to host registered, read-only cross-owner projections. Compatibility
entrypoints may remain at their historical import paths, but they cannot become service locators.

Exceptions require a dated ADR, an owner, a removal condition, and an architecture-test suppression
that names that ADR.

## Consequences

The deployment remains operationally simple. Module boundaries are enforced in code rather than
database schemas. Some workflows need explicit coordination and more precise DTOs, but provider,
transport, and persistence details can be tested independently from business policies.
