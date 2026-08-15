# Codex provenance

Extract only observable claims supported by the current chapter. Every fact, relationship,
event, identity reveal, alias, state transition, and plot-thread update needs at least one
supplied current-chapter chunk ID plus a short contiguous `evidence_text` span copied verbatim from
one cited chunk. Never stitch separated lines or omit intervening source words; for overlapping
chunks, cite the chunk containing the complete span. Claims may paraphrase, but the cited evidence
must semantically entail them; word overlap by itself is not proof. Never invent citations, database IDs, volume boundaries,
future knowledge, or destructive operations. References must resolve to a current mention or
supplied bounded-context ref. Memory updates must exactly match the supplied reducer targets,
copy every covered chapter, and partition that coverage once across substantive key beats.
Every mention `surface_form` must occur literally as a word-bounded span in the current chapter
chunks; inferred labels and normalized descriptions are not mention surfaces.
