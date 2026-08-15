# ADR-013: Canonicalize bounded verifier evidence selections to contiguous source

- Status: accepted
- Date: 2026-08-05

## Context

Chapter 149 failed both job attempts after independent verification. The retained claims were
semantically supported, but the verifier formatted a proposal and acceptance as one quote while
omitting the intervening narration. It did the same with a nearby marital-communication passage.
One other exact passage was attributed to the preceding overlapping chunk instead of the supplied
chunk containing the whole passage. Exact lexical locality therefore reported four or five bad
items and the broad-loss guard rejected the chapter.

Weakening locality to unordered overlap or semantic similarity would admit changed values and
misattributed claims. Dropping every affected item would lose the chapter's central developments.

## Decision

OpenAI Codex contract 1.3.9 retains artifact schema 2.2 and exact contiguous evidence locality.
Only a `codex_verify` artifact may enter a deterministic canonicalization step before residual
item quarantine:

- An anchor found exactly in another supplied current-chapter chunk is relocated to that chunk.
- Otherwise every verifier-selected token must occur unchanged and in order within one supplied
  chunk. The host restores the complete source slice from the first selected word through the last.
- Repair requires at least six selected tokens and allows at most 32 inserted tokens, 24 inserted
  tokens in one gap, three-times token expansion, and 1,200 source characters.
- Changed or reordered words, distant stitching, missing evidence, and every residual issue remain
  subject to the existing quarantine and broad-failure thresholds.

The verifier prompt additionally requires a contiguous quotation and correct overlap citation.
The atomic writer still validates the resulting exact source anchor against its locked chapter
snapshot. No persisted table or pipeline version changes.

## Consequences

- Both retained chapter-149 verifier artifacts canonicalize all nine malformed anchors with no
  information loss.
- Semantic approval remains mandatory; primary extraction cannot use this recovery.
- The host does not infer entailment or synthesize prose. It only restores literal nearby context
  around words already selected by the verifier.
- Adversarial changed-number, endpoint-reordering, and distant-stitch fixtures continue to fail.
- Already committed pipeline-2.1 chapters remain valid; uncommitted older-contract runs regenerate.
