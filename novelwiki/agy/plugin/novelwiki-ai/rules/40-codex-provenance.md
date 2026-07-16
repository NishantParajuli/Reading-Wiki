# Codex provenance

Extract only observable claims supported by the current chapter. Every fact, relationship,
event, identity reveal, alias, state transition, and plot-thread update needs at least one
supplied current-chapter chunk ID. Never invent citations, database IDs, volume boundaries,
future knowledge, or destructive operations. References must resolve to a current mention or
supplied bounded-context ref. Memory updates must exactly match the supplied reducer targets.
Every mention `surface_form` must occur literally as a word-bounded span in the current chapter
chunks; inferred labels and normalized descriptions are not mention surfaces.
