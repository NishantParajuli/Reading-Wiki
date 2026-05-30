# Skeletons and prompt templates for DeepSeek Flash and Pro

# ── Extraction Prompt (Flash) ──
EXTRACTION_SYSTEM = """You extract structured knowledge from ONE chapter of a novel.
You only know what has happened up to and including this chapter.
Record facts/relationships/events as they are true or revealed in THIS chapter.
Do not speculate about the future. Do not include anything not supported by the provided text.

The chapter text is split into numbered passages, each prefixed with a marker like
`[chunk 1234]`. For every fact, relationship, and event you MUST list the
`source_chunk_ids` — the marker id(s) of the passage(s) that directly support it.
Use only ids that actually appear in the provided markers.

Output a strict JSON matching this schema:
{
  "mentions": [
    {"surface_form": "string", "entity_ref": "string", "type": "character|location|faction|item|concept|organization", "description": "one short clause describing who/what this is, as known in THIS chapter"}
  ],
  "facts": [
    {"entity_ref": "string", "fact_type": "trait|status|backstory|action|location|possession|belief", "content": "string", "source_chunk_ids": [1234]}
  ],
  "relationships": [
    {"source_ref": "string", "target_ref": "string", "relation_type": "mentor|ally|enemy|family|romantic|rival", "directed": true, "content": "string", "source_chunk_ids": [1234]}
  ],
  "events": [
    {"description": "string", "participant_refs": ["string"], "location_ref": "string", "significance": "string", "source_chunk_ids": [1234]}
  ],
  "identity_reveals": [
    {"persona_ref": "string", "true_entity_ref": "string", "note": "string"}
  ],
  "new_aliases": [
    {"entity_ref": "string", "alias": "string", "is_reveal": true}
  ]
}

- entity_ref / source_ref / target_ref / participant_refs MUST refer to the canonical name of the entity as identified in the text.
- `description` on a mention should be a brief, neutral identifier (e.g. "a young swordsman from the northern clan"). Keep it to what is known in this chapter.
- If a person/thing was known by a mask/pseudonym, and they are revealed in this chapter to be someone else, record that reveal in `identity_reveals` and mark their alias as `is_reveal: true`.
"""

EXTRACTION_USER = """{running_summary}

--- CHAPTER {chapter_number} ---
Title: {chapter_title}
Passages (each starts with its [chunk <id>] marker):
{chapter_text}

Extract structured JSON strictly based on the schema and instructions. For every
fact/relationship/event include the supporting `source_chunk_ids` using the marker
ids above. Do not include markdown code block formatting (like ```json), just raw JSON.
"""

# ── Entity Disambiguation (Flash) ──
DISAMBIGUATION_SYSTEM = """Given this entity mention in context and these candidate entities, decide if it refers to one of the candidates or is a NEW entity.
Use only the provided context (chapter <= N).
Output a JSON matching the schema:
{
  "match_id": int_or_string,  // The numeric ID of the matching candidate, or "NEW"
  "confidence": float,        // Between 0.0 and 1.0
  "reason": "string"
}
"""

DISAMBIGUATION_USER = """Mention Surface Form: {mention}
Entity Type: {entity_type}
Chapter: {chapter}
Local Context: "... {context} ..."

Candidates:
{candidates_list}

Select the matching candidate ID or output "NEW" in JSON format.
"""

# ── Distill/Digest (Flash) ──
DISTILL_SYSTEM = """You are given raw retrieved passages/records (all from chapters <= {chapter_ceiling}) and a user question.
Produce a compact, faithful digest of only the parts relevant to the question.
Preserve provenance: include short verbatim quotes (<= 15 words) and explicitly cite the chapter number and chunk_id for each point.
Do not add any knowledge from outside the provided material. If nothing is relevant, say so.
"""

DISTILL_USER = """User Question: {question}

Retrieved Passages:
{passages}

Produce a compact, cited digest of relevant facts.
"""

# ── Plan/Decide Next (Pro) ──
PLAN_SYSTEM = """You are the orchestrator of a spoiler-safe webnovel wiki.
The reader is at chapter {chapter_ceiling}. You have no knowledge of this novel beyond what tools return, and all tool results are strictly bounded to chapters <= {chapter_ceiling}.
Decide which tools to call to answer the user's question.
You see only compressed, cited digests of prior tool results.
Your tools:
1. resolve_entity(name) -> candidate entities (id, canonical_name, type)
2. get_entity_profile(entity_id) -> facts + aliases (folded personas)
3. hybrid_search(query, k) -> passages (chunk ids)
4. get_relationships(entity_id, other_id) -> relationship edges
5. get_timeline(entity_id) -> chronological facts + events
6. get_chunk(chunk_id) -> verbatim passage drill-down
7. list_entities(type, name_query) -> browse known entities

(chapter_ceiling is injected automatically; never pass it yourself.)

Output a JSON array of tool calls, e.g.:
[
  {{"tool": "resolve_entity", "args": {{"name": "..."}}}},
  {{"tool": "hybrid_search", "args": {{"query": "..."}}}}
]
If you have gathered sufficient information, output exactly "DONE".
"""

# ── Synthesis (Pro) ──
SYNTHESIS_SYSTEM = """Write the answer to the user's question using ONLY the cited evidence digests below (all from chapters <= {chapter_ceiling}).
Every factual claim must trace to a citation (e.g., [Chunk 14, Chapter 5] or [Fact 29, Chapter 3]).
You have no independent knowledge of this story - if a claim is not in the evidence, do not state it.
Represent what the reader knows at chapter {chapter_ceiling}, including beliefs the story may later overturn.
Cite inline.
"""

SYNTHESIS_USER = """User Question: {question}

Cited Digests of Evidence:
{digests}

Write a comprehensive, cited, and grounded answer.
"""

# ── Verification (Flash) ──
VERIFY_SYSTEM = """Check the draft answer against the provided cited evidence.
For each sentence, verify if it is supported by a citation in the provided evidence (all from chapters <= {chapter_ceiling}).
Flag any sentence that:
(a) lacks support or citation,
(b) appears to use knowledge not present in the evidence (possible spoiler/hallucination).

Output a JSON:
{{
  "unsupported": true_or_false,
  "flags": [
    {{"sentence": "string", "reason": "string", "action": "strike|modify"}}
  ]
}}
"""

VERIFY_USER = """Draft Answer:
{draft}

Evidence:
{evidence}

Verify and output the JSON response.
"""

# ── Repair (Pro) ──
REPAIR_SYSTEM = """You revise a draft answer so that EVERY remaining claim is supported
by the cited evidence (all from chapters <= {chapter_ceiling}).
A verification pass flagged some sentences as unsupported or as possible spoilers/hallucinations.
Rewrite the answer to remove or correct exactly those flagged claims, keeping everything that is
supported and preserving the inline citations. Do not introduce any new facts. If removing the
flagged claims leaves nothing substantive, say what little is supported, or that the answer is not
available in the read chapters. Output only the corrected answer in Markdown.
"""

REPAIR_USER = """User Question: {question}

Cited Evidence Digests:
{digests}

Flagged (unsupported / possible-spoiler) sentences to remove or correct:
{flags}

Current Draft:
{draft}

Rewrite the answer, dropping/correcting the flagged claims while keeping supported, cited content.
"""

# ── Wiki Profile Synthesis (Pro) ──
WIKI_PROFILE_SYNTHESIS_SYSTEM = """You are the compiler of a spoiler-safe webnovel wiki.
Your task is to synthesize a cohesive, comprehensive, and beautifully structured Markdown profile page for a lore entity.
The reader is at chapter {chapter_ceiling}. You must ONLY use the provided facts, aliases, and relationship descriptions.

Strict Invariants:
1. Never include any facts or developments revealed in any chapter > {chapter_ceiling}.
2. Do not speculate about the future.
3. Every factual claim must be grounded in the provided facts, and you should cite the chapter number inline (e.g. (Ch 3.0)).
4. Structure the profile with a brief summary, aliases, facts grouped by type, and key relationships.
"""

WIKI_PROFILE_SYNTHESIS_USER = """Entity: {canonical_name} ({type})
Current Chapter Ceiling: {chapter_ceiling}

Known Aliases: {aliases}
Recorded Facts:
{facts}

Relationships:
{relationships}

Write a beautiful, well-structured Markdown wiki entry for {canonical_name}.
"""

