# ADR-010: Match regular possessive-number entity-name variants exactly

- Status: accepted
- Date: 2026-08-04

## Context

The trusted entity roster stored `Adventurer's Guild`, while chapter 41 consistently used the
grammatically plural possessive `Adventurers' Guild`. Two independent verifier attempts retained
that source wording. The exact claim matcher counted eight facts and three relationships as
separate alignment failures even though every finding had the same lexical root cause.

Quarantining those claims would discard a large, coherent part of the chapter. Treating the names
as fuzzy aliases would weaken the wrong-entity attachment boundary.

## Decision

OpenAI Codex contract 1.3.6 keeps artifact schema 2.2 and derives a regular
singular-possessive-to-plural-possessive variant of the complete trusted name for entities typed as
organizations, factions, or concepts. Claim matching normalizes Unicode apostrophe typography.

The transform changes only the possessive word and retains every other character in the entity
name. It does not stem, omit the possessive marker, calculate edit distance, or accept irregular
forms. The existing strict whole-name boundaries and broad-failure thresholds remain active.

## Consequences

- `Adventurer's Guild` and `Adventurers' Guild` align as the same organization term.
- `Adventurer Guild`, prefixes, and arbitrary near-matches remain invalid.
- Replaying both failed chapter-41 verifier artifacts produces zero claim-alignment issues for the
  trusted guild ref.
- Persisted schemas and existing pipeline-2.1 commits are unchanged.
