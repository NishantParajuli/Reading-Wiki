# ADR-009: Recover bounded claim-alignment failures without fuzzy matching

- Status: accepted
- Date: 2026-08-04

## Context

Claim/ref alignment prevents a readable fact from being stored against the wrong entity. A
chapter-39 verifier correctly changed the canonical concept name `Stone Treant` into the regular
plural `Stone Treants`, but the host's exact word-boundary matcher rejected the trailing `s`.
Both whole-job attempts then failed after the expensive verifier had otherwise produced a valid
chapter artifact.

Making alignment fuzzy would hide real wrong-entity attachments. Requiring the verifier to keep
retrying every isolated wording miss would continue turning one bad claim into a failed long build.

## Decision

OpenAI Codex contract 1.3.5 keeps artifact schema 2.2 and makes two bounded changes:

- For entities typed as concepts or items, the host derives a conservative regular plural of the
  complete accepted name. It does not stem, truncate, or use similarity. Character and location
  names do not receive this exception.
- After independent verification, isolated residual alignment failures are quarantined at the
  fact, relationship, or event item boundary. Two or more failures at 40% or more of claim output,
  or more than three failures, reject the chapter with `claim_alignment_broad_failure`.

The surviving artifact is revalidated with the strict reference graph before entity resolution
and commit. Worker-loss recovery applies the same policy to a complete verifier artifact.

## Consequences

- `Stone Treant` and `Stone Treants` align, while `Stone Treantling` does not.
- A wrong subject or endpoint is never made valid by approximate text matching.
- One unrepaired claim cannot consume the final attempt of an otherwise valid long build.
- Broad verifier degradation remains visible and retryable instead of silently discarding a large
  part of a chapter.
- Database and pipeline schemas are unchanged; already committed pipeline-2.1 chapters remain
  valid.
