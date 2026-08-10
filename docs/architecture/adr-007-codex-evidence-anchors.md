# ADR-007: Ground Codex claims with evidence anchors, not shared words

- Status: accepted
- Date: 2026-08-03

## Context

Codex artifact schema 2.1 tried to prove citation locality by requiring two meaningful words
from each reader-facing claim to occur in its cited chunk. That check rejected valid paraphrases.
For example, a claim that a son thanked his mother for giving birth to him was supported by the
dialogue “thank you for having me,” but the wording gate rejected the complete chapter after the
independent verifier had already approved it. Reducing the overlap threshold would admit unrelated
claims that happen to share names or topic words and would still mishandle synonyms, morphology,
pronouns, and dialogue attribution.

## Decision

Codex extraction artifact schema 2.2 requires every fact, relationship, event, identity reveal,
alias, entity/relationship state transition, and thread update to carry both:

- one or more supplied current-chapter `source_chunk_ids`; and
- a short `evidence_text` span copied verbatim from one cited chunk.

The trusted host normalizes only Unicode presentation, case, surrounding quotation marks, and
whitespace before checking that the anchor occurs inside one cited chunk. It does not compare claim
vocabulary with passage vocabulary. Reader-facing claims may therefore be useful paraphrases.
Semantic entailment remains the responsibility of the independent verifier, whose task explicitly
requires it to repair or drop claims that are merely topically related, contradicted, or unsupported.
Host-detected anchor locations from the draft are included in that verification task as targeted
repair instructions.

After verification, one isolated bad anchor is quarantined without discarding valid chapter
material. Up to three isolated items may be quarantined while they remain below 40% of the chapter's
material claims. Two or more failures at or above that ratio, or more than three failures, reject the
chapter for retry rather than silently accepting broad information loss. Removing an identity reveal
also removes its dependent identity-state transition. Quarantine diagnostics contain only group,
index, and reason metadata; they never echo story text.

The persisted database pipeline remains version 2.1 because its row shape and read semantics are
unchanged: stored claims still cite chunk IDs, and the cited source remains retrievable. The artifact
contract moves independently to 2.2. OpenAI Codex contract 1.3.3 and AGY plugin 1.4.3 identify the
new prompts and validators.

Retry progress is based on committed chapters and source chapter numbers. A whole-job retry no
longer presents its first remaining chapter as “chapter 1” or leaves the frontend's progress stage
at preprocessing.

## Consequences

- Valid paraphrases no longer fail solely because they use different words from the source.
- Literal anchors give the host deterministic citation-locality enforcement without pretending to
  perform semantic reasoning.
- The independent Luna/xhigh verifier remains mandatory for the OpenAI Codex backend and is the
  semantic quality gate.
- A single malformed item cannot waste an otherwise valid chapter, while broad grounding failure
  still fails closed.
- No database migration or completed-chapter rebuild is required. Uncommitted 2.1 artifacts are not
  resumable under the 2.2 worker contract and must be regenerated after worker activation.
