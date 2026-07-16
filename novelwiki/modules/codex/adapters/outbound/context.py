from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from novelwiki.modules.codex.adapters.outbound.ingest.chunk import get_encoder
from novelwiki.platform.config import settings


_MULTI_STATE_KEYS = {"affiliation", "possession", "ability", "identity", "title", "goal", "knowledge"}
_NARRATIVE_KINDS = {"chapter", "interlude"}
_TITLE_SPAN = re.compile(
    r"\b[A-Z][\w'’.-]*(?:\s+(?:(?:of|the|and|de|von|van)\s+)?[A-Z][\w'’.-]*){0,4}\b"
)


def count_tokens(text: str) -> int:
    return len(get_encoder().encode(text or ""))


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _without_provenance(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_provenance(child)
            for key, child in value.items()
            if key not in {"source_chunk_ids", "transition_id"}
        }
    if isinstance(value, list):
        return [_without_provenance(child) for child in value]
    return value


def _visible_occurrence(term: str, text: str) -> bool:
    term = (term or "").strip()
    if len(term) < 3:
        return False
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE) is not None


def _extract_title_spans(text: str, limit: int = 40) -> list[str]:
    result = []
    seen = set()
    for match in _TITLE_SPAN.finditer(text or ""):
        value = match.group(0).strip(" .,:;!?()[]{}\"'")
        normalized = value.casefold()
        if len(value) < 3 or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _apply_transition(state: dict[str, Any], row: dict) -> None:
    key = row["state_key"]
    operation = row["operation"]
    value = row.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            pass
    if row.get("narrative_scope", "current") != "current":
        return
    entry = {
        "value": value,
        "certainty": row.get("certainty") or "confirmed",
        "perspective": row.get("perspective"),
        "chapter": float(row["chapter"]),
        "transition_id": int(row["id"]),
        "source_chunk_ids": list(row.get("source_chunk_ids") or []),
    }
    if key in _MULTI_STATE_KEYS:
        current = list(state.get(key) or [])
        if operation == "set":
            current = [] if value is None else [entry]
        elif operation in {"add", "confirm"} and value is not None:
            current = [
                item for item in current
                if (item.get("value") if isinstance(item, dict) else item) != value
            ]
            current.append(entry)
        elif operation in {"remove", "contradict"}:
            current = [
                item for item in current
                if (item.get("value") if isinstance(item, dict) else item) != value
            ]
        elif operation == "clear":
            current = []
        if current:
            state[key] = current
        else:
            state.pop(key, None)
        return
    if operation in {"set", "add", "confirm"}:
        state[key] = entry
    elif operation == "clear" or (
        operation in {"remove", "contradict"}
        and (
            state.get(key, {}).get("value")
            if isinstance(state.get(key), dict) else state.get(key)
        ) == value
    ):
        state.pop(key, None)


async def current_entity_state(
    conn, novel_id: int, entity_ids: list[int], chapter_ceiling: float,
) -> dict[int, dict[str, Any]]:
    if not entity_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT s.id,s.entity_id,s.state_key,s.operation,s.value,s.certainty,s.narrative_scope,
               s.source_chunk_ids,
               s.chapter,s.id,p.canonical_name perspective
        FROM entity_state_transitions s
        LEFT JOIN entities p ON p.id=s.perspective_entity_id
        WHERE s.novel_id=$1 AND s.entity_id=ANY($2::bigint[]) AND s.chapter <= $3
          AND s.pipeline_version=$4
        ORDER BY s.chapter,s.id;
        """,
        novel_id, entity_ids, chapter_ceiling, settings.CODEX_PIPELINE_VERSION,
    )
    result: dict[int, dict[str, Any]] = defaultdict(dict)
    for raw in rows:
        row = dict(raw)
        _apply_transition(result[int(row["entity_id"])], row)
    return dict(result)


async def current_relationship_state(
    conn, novel_id: int, entity_ids: list[int], chapter_ceiling: float, *,
    require_both_endpoints: bool = False,
) -> list[dict[str, Any]]:
    """Return only the latest still-active value for each relationship-state key."""
    if not entity_ids:
        return []
    endpoint_filter = (
        "source_id=ANY($2::bigint[]) AND target_id=ANY($2::bigint[])"
        if require_both_endpoints
        else "(source_id=ANY($2::bigint[]) OR target_id=ANY($2::bigint[]))"
    )
    rows = await conn.fetch(
        f"""
        WITH latest AS (
          SELECT DISTINCT ON (source_id,target_id,state_key)
            source_id,target_id,state_key,operation,value,certainty,chapter,id,source_chunk_ids
          FROM relationship_state_transitions
          WHERE novel_id=$1 AND {endpoint_filter} AND chapter <= $3
            AND pipeline_version=$4
          ORDER BY source_id,target_id,state_key,chapter DESC,id DESC
        )
        SELECT l.*,source.canonical_name source_name,target.canonical_name target_name
        FROM latest l
        JOIN entities source ON source.id=l.source_id AND source.novel_id=$1
        JOIN entities target ON target.id=l.target_id AND target.novel_id=$1
        WHERE l.operation IN ('set','add','confirm')
        ORDER BY l.chapter DESC,l.id DESC
        LIMIT $5;
        """,
        novel_id, entity_ids, chapter_ceiling, settings.CODEX_PIPELINE_VERSION,
        settings.CODEX_READ_MAX_RELATIONSHIPS,
    )
    return [
        {
            **dict(row),
            "source_id": int(row["source_id"]),
            "target_id": int(row["target_id"]),
            "chapter": float(row["chapter"]),
            "value": json.loads(row["value"]) if isinstance(row["value"], str) else row["value"],
        }
        for row in rows
    ]


def _chapter_memory_shape(chapter: float, metadata: dict | None) -> dict:
    metadata = metadata or {
        "kind": "chapter", "part_label": None, "narrative_part_chapters": [chapter],
    }
    kind = metadata.get("kind") or "chapter"
    if kind not in _NARRATIVE_KINDS:
        return {
            "narrative": False, "kind": kind, "part_label": metadata.get("part_label"),
            "memory_targets": [], "block_numbers": [],
        }
    numbers = [float(number) for number in metadata.get("narrative_part_chapters") or []]
    try:
        index = numbers.index(float(chapter))
    except ValueError:
        return {"narrative": False, "memory_targets": [], "block_numbers": []}
    width = max(1, settings.CODEX_CHECKPOINT_CHAPTERS)
    block_start_index = (index // width) * width
    block_end_index = min(block_start_index + width - 1, len(numbers) - 1)
    at_fixed_boundary = index == block_start_index + width - 1
    at_labeled_part_end = bool(metadata.get("part_label")) and index == len(numbers) - 1
    closes_checkpoint = at_fixed_boundary or at_labeled_part_end
    # Carry the bounded open block as grounded child summaries on every chapter.
    # A reducer target is still emitted only when the block actually closes.
    block_numbers = numbers[block_start_index:index]
    checkpoint = {
        "kind": "checkpoint",
        "start_chapter": numbers[block_start_index],
        "end_chapter": numbers[block_end_index],
        "through_chapter": float(chapter),
        "part_label": metadata.get("part_label"),
    }
    targets = [checkpoint] if closes_checkpoint else []
    if at_labeled_part_end:
        targets.append({
            "kind": "volume",
            "start_chapter": numbers[0],
            "end_chapter": numbers[-1],
            "through_chapter": float(chapter),
            "part_label": metadata.get("part_label"),
        })
    return {
        "narrative": True, "kind": kind, "part_label": metadata.get("part_label"),
        "memory_targets": targets, "block_numbers": block_numbers,
        "part_numbers": numbers, "block_start_index": block_start_index,
    }


async def _candidate_scores(conn, novel_id: int, chapter: float, content: str) -> tuple[dict[int, float], dict[int, set[str]]]:
    scores: dict[int, float] = defaultdict(float)
    reasons: dict[int, set[str]] = defaultdict(set)
    visible = await conn.fetch(
        """
        SELECT e.id,e.canonical_name,
               COALESCE(array_agg(DISTINCT a.alias ORDER BY a.alias) FILTER (WHERE a.alias IS NOT NULL),'{}') aliases
        FROM entities e
        LEFT JOIN entity_aliases a ON a.entity_id=e.id AND a.revealed_at_chapter < $2
        WHERE e.novel_id=$1 AND e.first_seen_chapter < $2
          AND (strpos(lower($3),lower(e.canonical_name))>0 OR EXISTS (
              SELECT 1 FROM entity_aliases ax
              WHERE ax.entity_id=e.id AND ax.revealed_at_chapter < $2
                AND length(ax.alias)>=3 AND strpos(lower($3),lower(ax.alias))>0
          ))
        GROUP BY e.id ORDER BY e.id
        LIMIT 300;
        """,
        novel_id, chapter, content,
    )
    for row in visible:
        names = [row["canonical_name"], *(row["aliases"] or [])]
        if any(_visible_occurrence(name, content) for name in names):
            entity_id = int(row["id"])
            scores[entity_id] += 1000
            reasons[entity_id].add("exact_chapter_term")

    recent_floor = chapter - settings.CODEX_RECENT_ACTIVITY_CHAPTERS
    recent = await conn.fetch(
        """
        SELECT entity_id,max(chapter) last_seen,
               sum(mention_count+claim_count+event_count) activity
        FROM entity_activity
        WHERE novel_id=$1 AND chapter < $2 AND chapter >= $3
          AND pipeline_version=$4
        GROUP BY entity_id ORDER BY last_seen DESC,activity DESC,entity_id LIMIT 150;
        """,
        novel_id, chapter, recent_floor, settings.CODEX_PIPELINE_VERSION,
    )
    for row in recent:
        entity_id = int(row["entity_id"])
        distance = max(0.0, chapter - float(row["last_seen"]))
        scores[entity_id] += max(50.0, 350.0 - distance * 20.0)
        reasons[entity_id].add("recent_activity")

    # V1 compatibility: activity rows do not exist yet, so recently introduced
    # entities still seed the bounded roster during an in-place migration.
    if not recent:
        introduced = await conn.fetch(
            """
            SELECT id FROM entities WHERE novel_id=$1 AND first_seen_chapter < $2
              AND first_seen_chapter >= $3 ORDER BY first_seen_chapter DESC,id LIMIT 100;
            """,
            novel_id, chapter, recent_floor,
        )
        for row in introduced:
            entity_id = int(row["id"])
            scores[entity_id] += 175
            reasons[entity_id].add("v1_recently_introduced_fallback")

    thread_rows = await conn.fetch(
        """
        SELECT t.stable_title,u.operation,u.participants,u.keywords,u.chapter
        FROM plot_threads t
        JOIN LATERAL (
          SELECT operation,participants,keywords,chapter,id
          FROM plot_thread_updates
          WHERE novel_id=$1 AND thread_id=t.id AND chapter < $2 AND pipeline_version=$3
          ORDER BY chapter DESC,id DESC LIMIT 1
        ) u ON TRUE
        WHERE t.novel_id=$1 AND t.pipeline_version=$3
          AND u.operation NOT IN ('resolve','mark_dormant')
        ORDER BY u.chapter DESC,t.id LIMIT 50;
        """,
        novel_id, chapter, settings.CODEX_PIPELINE_VERSION,
    )
    for row in thread_rows:
        explicit = _visible_occurrence(row["stable_title"], content) or any(
            _visible_occurrence(keyword, content) for keyword in (row["keywords"] or [])
        )
        recent_thread = chapter - float(row["chapter"]) <= settings.CODEX_RECENT_ACTIVITY_CHAPTERS
        if not explicit and not recent_thread:
            continue
        for entity_id in row["participants"] or []:
            entity_id = int(entity_id)
            scores[entity_id] += 225 if explicit else 80
            reasons[entity_id].add("unresolved_thread")

    seed_ids = [
        entity_id for entity_id, _score in sorted(
            ((entity_id, score) for entity_id, score in scores.items() if score >= 200),
            key=lambda item: (-item[1], item[0]),
        )[:20]
    ]
    if seed_ids:
        connected = await conn.fetch(
            """
            WITH edges AS (
              SELECT seed_id,
                     CASE WHEN source_id=seed_id THEN target_id ELSE source_id END entity_id,
                     max(chapter) last_connected
              FROM relationships
              CROSS JOIN LATERAL unnest($2::bigint[]) AS seeds(seed_id)
              WHERE novel_id=$1 AND chapter < $3
                AND (source_id=seed_id OR target_id=seed_id)
              GROUP BY seed_id,2
            ), ranked AS (
              SELECT *,row_number() OVER (
                PARTITION BY seed_id ORDER BY last_connected DESC,entity_id
              ) neighbor_rank
              FROM edges
            )
            SELECT entity_id,max(last_connected) last_connected
            FROM ranked WHERE neighbor_rank <= 5
            GROUP BY entity_id ORDER BY last_connected DESC,entity_id LIMIT 100;
            """,
            novel_id, seed_ids, chapter,
        )
        for row in connected:
            entity_id = int(row["entity_id"])
            scores[entity_id] += 125
            reasons[entity_id].add("connected_to_candidate")

    spans = _extract_title_spans(content)
    if spans:
        fuzzy = await conn.fetch(
            """
            WITH spans(term) AS (SELECT unnest($3::text[])), candidates AS (
              SELECT e.id,max(similarity(e.canonical_name,spans.term)) score
              FROM entities e CROSS JOIN spans
              WHERE e.novel_id=$1 AND e.first_seen_chapter < $2
              GROUP BY e.id
              HAVING max(similarity(e.canonical_name,spans.term)) > $4
              UNION ALL
              SELECT a.entity_id,max(similarity(a.alias,spans.term)) score
              FROM entity_aliases a CROSS JOIN spans
              JOIN entities e ON e.id=a.entity_id
              WHERE a.novel_id=$1 AND a.revealed_at_chapter < $2 AND e.first_seen_chapter < $2
              GROUP BY a.entity_id
              HAVING max(similarity(a.alias,spans.term)) > $4
            )
            SELECT id,max(score) score FROM candidates GROUP BY id ORDER BY score DESC,id LIMIT 50;
            """,
            novel_id, chapter, spans, settings.FUZZY_MATCH_THRESHOLD,
        )
        for row in fuzzy:
            entity_id = int(row["id"])
            scores[entity_id] += float(row["score"]) * 100
            reasons[entity_id].add("trigram_chapter_span")

    # Reuse already-paid chunk/name embeddings. Avoid approximate HNSW here: an
    # exact grouped scan over the bounded current chapter is deterministic, which
    # is required when the commit rechecks the context hash.
    semantic = await conn.fetch(
        """
        SELECT e.id,max(1-(e.name_embedding <=> c.embedding)) score
        FROM entities e
        JOIN chunks c ON c.novel_id=e.novel_id AND c.chapter=$2 AND c.embedding IS NOT NULL
        WHERE e.novel_id=$1 AND e.first_seen_chapter < $2 AND e.name_embedding IS NOT NULL
        GROUP BY e.id ORDER BY score DESC,e.id LIMIT 20;
        """,
        novel_id, chapter,
    )
    for row in semantic:
        similarity = float(row["score"])
        if similarity < settings.CODEX_CONTEXT_VECTOR_MIN_SIMILARITY:
            continue
        entity_id = int(row["id"])
        scores[entity_id] += similarity * 50
        reasons[entity_id].add("chapter_vector")
    return scores, reasons


async def _thread_context(
    conn, novel_id: int, chapter: float, content: str, selected_refs: dict[int, str],
) -> tuple[list[dict], dict[str, int]]:
    rows = await conn.fetch(
        """
        SELECT t.id,t.stable_title,u.operation,u.summary,u.participants,u.keywords,u.chapter
        FROM plot_threads t
        JOIN LATERAL (
          SELECT operation,summary,participants,keywords,chapter,id
          FROM plot_thread_updates
          WHERE novel_id=$1 AND thread_id=t.id AND chapter < $2 AND pipeline_version=$3
          ORDER BY chapter DESC,id DESC LIMIT 1
        ) u ON TRUE
        WHERE t.novel_id=$1 AND t.pipeline_version=$3 AND t.introduced_at_chapter < $2
        ORDER BY u.chapter DESC,t.id LIMIT 100;
        """,
        novel_id, chapter, settings.CODEX_PIPELINE_VERSION,
    )
    ranked = []
    for row in rows:
        if row["operation"] in {"resolve", "mark_dormant"}:
            continue
        participants = {int(value) for value in (row["participants"] or [])}
        keyword_match = any(_visible_occurrence(value, content) for value in (row["keywords"] or []))
        title_match = _visible_occurrence(row["stable_title"], content)
        connected = bool(participants & set(selected_refs))
        recency = max(0.0, 100.0 - (chapter - float(row["chapter"])) * 5.0)
        score = (300 if title_match else 0) + (200 if keyword_match else 0) + (150 if connected else 0) + recency
        if score <= 0:
            continue
        ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], int(item[1]["id"])))
    result, mapping, used = [], {}, 0
    for index, (_score, row) in enumerate(ranked[:settings.CODEX_CONTEXT_MAX_THREADS], 1):
        participants = {int(value) for value in (row["participants"] or [])}
        item = {
            "thread_ref": f"t{index}", "title": row["stable_title"],
            "status": row["operation"], "summary": row["summary"],
            "participants": [selected_refs[value] for value in sorted(participants) if value in selected_refs],
        }
        item_tokens = count_tokens(_compact(item))
        if used + item_tokens > settings.CODEX_CONTEXT_THREAD_TOKENS:
            break
        used += item_tokens
        result.append(item)
        mapping[item["thread_ref"]] = int(row["id"])
    return result, mapping


async def build_chapter_context(
    conn, novel_id: int, chapter: float, content: str, chapter_metadata: dict | None = None,
    *, chapter_input_text: str | None = None,
) -> dict:
    shape = _chapter_memory_shape(chapter, chapter_metadata)
    scores, reasons = await _candidate_scores(conn, novel_id, chapter, content)
    ranked_ids = [entity_id for entity_id, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
    details = []
    if ranked_ids:
        rows = await conn.fetch(
            """
            SELECT e.id,e.canonical_name,e.type,e.first_seen_chapter,
                   COALESCE(d.description,e.description,'') description,
                   COALESCE(array_agg(DISTINCT a.alias ORDER BY a.alias) FILTER (WHERE a.alias IS NOT NULL),'{}') aliases
            FROM entities e
            LEFT JOIN LATERAL (
              SELECT description FROM entity_descriptions
              WHERE entity_id=e.id AND chapter < $2 ORDER BY chapter DESC LIMIT 1
            ) d ON TRUE
            LEFT JOIN entity_aliases a ON a.entity_id=e.id AND a.revealed_at_chapter < $2
            WHERE e.novel_id=$1 AND e.id=ANY($3::bigint[]) AND e.first_seen_chapter < $2
            GROUP BY e.id,d.description;
            """,
            novel_id, chapter, ranked_ids,
        )
        by_id = {int(row["id"]): row for row in rows}
        details = [by_id[entity_id] for entity_id in ranked_ids if entity_id in by_id]

    selected, roster_map, used_tokens, dropped = [], {}, 0, []
    for row in details:
        entity_id = int(row["id"])
        aliases = [
            alias for alias in (row["aliases"] or [])
            if alias.casefold() != row["canonical_name"].casefold()
        ][:20]
        ref = f"e{len(selected)+1}"
        item = {
            "entity_ref": ref, "canonical_name": row["canonical_name"], "type": row["type"],
            "aliases": aliases, "first_seen_chapter": float(row["first_seen_chapter"]),
            "identity_blurb": (row["description"] or "")[:500],
        }
        item_tokens = count_tokens(_compact(item))
        if len(selected) >= settings.CODEX_CONTEXT_MAX_ENTITIES or used_tokens + item_tokens > settings.CODEX_CONTEXT_ENTITY_TOKENS:
            dropped.append({"entity_id": entity_id, "reason": "entity_budget"})
            continue
        used_tokens += item_tokens
        selected.append(item)
        roster_map[ref] = entity_id

    state_by_id = await current_entity_state(conn, novel_id, list(roster_map.values()), chapter - 0.000001)
    state_items, state_tokens = [], 0
    for ref, entity_id in roster_map.items():
        if not state_by_id.get(entity_id):
            continue
        item = {"entity_ref": ref, "state": state_by_id[entity_id]}
        item["state"] = _without_provenance(item["state"])
        item_tokens = count_tokens(_compact(item))
        if state_tokens + item_tokens > settings.CODEX_CONTEXT_STATE_TOKENS:
            continue
        state_tokens += item_tokens
        state_items.append(item)

    id_to_ref = {entity_id: ref for ref, entity_id in roster_map.items()}
    relationship_state_items = []
    relationship_states = await current_relationship_state(
        conn, novel_id, list(roster_map.values()), chapter - 0.000001,
        require_both_endpoints=True,
    )
    for row in relationship_states:
        item = {
            "source_ref": id_to_ref[row["source_id"]],
            "target_ref": id_to_ref[row["target_id"]],
            "state_key": row["state_key"],
            "value": row["value"],
            "certainty": row["certainty"],
            "chapter": row["chapter"],
        }
        item_tokens = count_tokens(_compact(item))
        if state_tokens + item_tokens > settings.CODEX_CONTEXT_STATE_TOKENS:
            continue
        state_tokens += item_tokens
        relationship_state_items.append(item)

    threads, thread_map = await _thread_context(
        conn, novel_id, chapter, content,
        {entity_id: ref for ref, entity_id in roster_map.items()},
    )
    recent_rows = await conn.fetch(
        """
        SELECT chapter,summary,evidence_chunk_ids FROM chapter_summaries
        WHERE novel_id=$1 AND chapter < $2 AND pipeline_version=$3
        ORDER BY chapter DESC LIMIT $4;
        """,
        novel_id, chapter, settings.CODEX_PIPELINE_VERSION,
        settings.CODEX_RECENT_SUMMARY_CHAPTERS,
    )
    recent_summaries = [
        {"chapter": float(row["chapter"]), "summary": row["summary"]}
        for row in reversed(recent_rows)
    ]
    block_rows = []
    if shape["block_numbers"]:
        block_rows = await conn.fetch(
            """
            SELECT chapter,summary,evidence_chunk_ids,source_sha256 FROM chapter_summaries
            WHERE novel_id=$1 AND chapter=ANY($2::numeric[]) AND pipeline_version=$3
            ORDER BY chapter;
            """,
            novel_id, shape["block_numbers"], settings.CODEX_PIPELINE_VERSION,
        )
    block_row_chapters = {float(row["chapter"]) for row in block_rows}
    missing_block_chapters = set(shape["block_numbers"]) - block_row_chapters
    if missing_block_chapters:
        raise RuntimeError(
            "hierarchical memory prerequisites are missing before chapter "
            f"{chapter}: {sorted(missing_block_chapters)}; build v2 chronologically"
        )
    if shape.get("block_start_index", 0) > 0:
        width = max(1, settings.CODEX_CHECKPOINT_CHAPTERS)
        previous_start_index = max(0, shape["block_start_index"] - width)
        previous_start = shape["part_numbers"][previous_start_index]
        previous_end = shape["part_numbers"][shape["block_start_index"] - 1]
        previous_checkpoint = await conn.fetchval(
            """
            SELECT EXISTS(
              SELECT 1 FROM memory_segments
              WHERE novel_id=$1 AND kind='checkpoint' AND start_chapter=$2
                AND end_chapter=$3 AND through_chapter=end_chapter
                AND part_label IS NOT DISTINCT FROM $4 AND pipeline_version=$5
            );
            """,
            novel_id, previous_start, previous_end, shape.get("part_label"),
            settings.CODEX_PIPELINE_VERSION,
        )
        if not previous_checkpoint:
            raise RuntimeError(
                f"completed checkpoint {previous_start}–{previous_end} is missing; "
                "build v2 chronologically"
            )
    checkpoint_children = [
        {"chapter": float(row["chapter"]), "summary": row["summary"],
         "evidence_chunk_ids": list(row["evidence_chunk_ids"] or []),
         "source_sha256": row["source_sha256"]}
        for row in block_rows
    ]
    checkpoint_child_chapters = {item["chapter"] for item in checkpoint_children}
    recent_summaries = [
        item for item in recent_summaries if item["chapter"] not in checkpoint_child_chapters
    ]
    volume_children = []
    if any(target["kind"] == "volume" for target in shape["memory_targets"]):
        volume_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (start_chapter,end_chapter)
              start_chapter,end_chapter,through_chapter,summary,source_hash
            FROM memory_segments
            WHERE novel_id=$1 AND kind='checkpoint' AND part_label IS NOT DISTINCT FROM $2
              AND through_chapter=end_chapter AND through_chapter < $3 AND pipeline_version=$4
            ORDER BY start_chapter,end_chapter,through_chapter DESC,created_at DESC;
            """,
            novel_id, shape.get("part_label"), chapter, settings.CODEX_PIPELINE_VERSION,
        )
        volume_children = [
            {"start_chapter": float(row["start_chapter"]),
             "end_chapter": float(row["end_chapter"]),
             "through_chapter": float(row["through_chapter"]),
             "summary": row["summary"], "source_hash": row["source_hash"]}
            for row in volume_rows
        ]
        covered = {*shape["block_numbers"], float(chapter)}
        for child in volume_children:
            covered.update(
                number for number in shape["part_numbers"]
                if child["start_chapter"] <= number <= child["through_chapter"]
            )
        if covered != set(shape["part_numbers"]):
            missing = sorted(set(shape["part_numbers"]) - covered)
            raise RuntimeError(
                f"volume reducer lacks completed checkpoint coverage for chapters {missing}; "
                "build v2 chronologically"
            )
    completed = await conn.fetch(
        """
        WITH latest_checkpoint AS (
          SELECT kind,start_chapter,end_chapter,through_chapter,part_label,summary
          FROM memory_segments
          WHERE novel_id=$1 AND kind='checkpoint' AND through_chapter=end_chapter
            AND through_chapter < $2
            AND pipeline_version=$3
          ORDER BY through_chapter DESC,created_at DESC LIMIT 1
        ), latest_volume AS (
          SELECT kind,start_chapter,end_chapter,through_chapter,part_label,summary
          FROM memory_segments
          WHERE novel_id=$1 AND kind='volume' AND end_chapter < $2
            AND pipeline_version=$3
          ORDER BY through_chapter DESC,created_at DESC LIMIT 1
        )
        SELECT * FROM latest_checkpoint UNION ALL SELECT * FROM latest_volume
        ORDER BY through_chapter;
        """,
        novel_id, chapter, settings.CODEX_PIPELINE_VERSION,
    )
    completed_memory = [
        {"kind": row["kind"], "start_chapter": float(row["start_chapter"]),
         "end_chapter": float(row["end_chapter"]), "through_chapter": float(row["through_chapter"]),
         "part_label": row["part_label"], "summary": row["summary"]}
        for row in reversed(completed)
    ]

    context = {
        "pipeline_version": settings.CODEX_PIPELINE_VERSION,
        "ceiling": chapter - 0.000001,
        "entities": selected,
        "current_state": state_items,
        "current_relationship_state": relationship_state_items,
        "recent_chapter_summaries": recent_summaries,
        "completed_memory": completed_memory,
        "current_checkpoint_children": checkpoint_children,
        "completed_volume_checkpoint_children": volume_children,
        "open_threads": threads,
        "memory_targets": shape["memory_targets"],
        "source_kind": shape.get("kind"),
        "part_label": shape.get("part_label"),
    }
    serialized = _compact(context)
    context_tokens = count_tokens(serialized)
    # Extraction sees overlapping chunk-marked text, which can be materially
    # larger than raw chapter content. Callers pass that exact transport text so
    # budget-driven reductions remain reproducible at commit time.
    chapter_tokens = count_tokens(chapter_input_text if chapter_input_text is not None else content)
    total_estimate = context_tokens + chapter_tokens + 3_000
    # Keep the invariant fail-closed. Individual section caps normally prevent
    # this, but a dense checkpoint/volume reducer input can still be exceptional.
    if total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS:
        while context["completed_memory"] and total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS:
            context["completed_memory"].pop(0)
            serialized = _compact(context)
            context_tokens = count_tokens(serialized)
            total_estimate = context_tokens + chapter_tokens + 3_000
        while context["open_threads"] and total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS:
            removed = context["open_threads"].pop()
            thread_map.pop(removed["thread_ref"], None)
            serialized = _compact(context)
            context_tokens = count_tokens(serialized)
            total_estimate = context_tokens + chapter_tokens + 3_000
        while context["current_relationship_state"] and total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS:
            context["current_relationship_state"].pop()
            serialized = _compact(context)
            context_tokens = count_tokens(serialized)
            total_estimate = context_tokens + chapter_tokens + 3_000
        while context["current_state"] and total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS:
            context["current_state"].pop()
            serialized = _compact(context)
            context_tokens = count_tokens(serialized)
            total_estimate = context_tokens + chapter_tokens + 3_000
        while context["entities"] and total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS:
            removed = context["entities"].pop()
            removed_id = roster_map.pop(removed["entity_ref"], None)
            dropped.append({"entity_id": removed_id, "reason": "total_context_budget"})
            context["current_state"] = [
                item for item in context["current_state"]
                if item["entity_ref"] != removed["entity_ref"]
            ]
            context["current_relationship_state"] = [
                item for item in context["current_relationship_state"]
                if removed["entity_ref"] not in {item["source_ref"], item["target_ref"]}
            ]
            for thread in context["open_threads"]:
                thread["participants"] = [
                    ref for ref in thread["participants"] if ref != removed["entity_ref"]
                ]
            serialized = _compact(context)
            context_tokens = count_tokens(serialized)
            total_estimate = context_tokens + chapter_tokens + 3_000
        has_checkpoint_target = any(
            target["kind"] == "checkpoint" for target in context["memory_targets"]
        )
        while (not has_checkpoint_target and context["current_checkpoint_children"]
               and total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS):
            context["current_checkpoint_children"].pop(0)
            serialized = _compact(context)
            context_tokens = count_tokens(serialized)
            total_estimate = context_tokens + chapter_tokens + 3_000
        if total_estimate > settings.CODEX_CONTEXT_MAX_TOKENS:
            raise RuntimeError(
                f"chapter plus grounded reducer inputs exceed hard budget: estimated {total_estimate} > "
                f"{settings.CODEX_CONTEXT_MAX_TOKENS} tokens"
            )

    final_identity_tokens = count_tokens(_compact(context["entities"]))
    final_state_tokens = count_tokens(_compact({
        "entity": context["current_state"],
        "relationship": context["current_relationship_state"],
    }))
    final_thread_tokens = count_tokens(_compact(context["open_threads"]))
    manifest = {
        "pipeline_version": settings.CODEX_PIPELINE_VERSION,
        "chapter": chapter,
        "selected_entities": [
            {"entity_id": roster_map[item["entity_ref"]],
             "score": scores[roster_map[item["entity_ref"]]],
             "reasons": sorted(reasons[roster_map[item["entity_ref"]]])}
            for item in context["entities"]
        ],
        "dropped_entities": dropped,
        "thread_ids": list(thread_map.values()),
        "recent_summary_chapters": [item["chapter"] for item in recent_summaries],
        "checkpoint_child_chapters": [item["chapter"] for item in context["current_checkpoint_children"]],
        "checkpoint_child_source_hashes": [
            {"chapter": item["chapter"], "source_sha256": item["source_sha256"]}
            for item in context["current_checkpoint_children"]
        ],
        "volume_checkpoint_ranges": [
            [item["start_chapter"], item["end_chapter"]]
            for item in context["completed_volume_checkpoint_children"]
        ],
        "volume_checkpoint_source_hashes": [
            item["source_hash"] for item in context["completed_volume_checkpoint_children"]
        ],
        "memory_targets": context["memory_targets"],
        "tokens": {
            "chapter": chapter_tokens, "context": context_tokens,
            "entity_identity": final_identity_tokens, "entity_state": final_state_tokens,
            "threads": final_thread_tokens,
            "estimated_total": total_estimate,
        },
    }
    context_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return {
        "context": context, "serialized": serialized, "manifest": manifest,
        "context_sha256": context_sha256, "token_count": context_tokens,
        "roster_map": roster_map, "thread_map": thread_map,
        "memory_targets": context["memory_targets"],
    }
