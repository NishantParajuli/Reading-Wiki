/* Pure presentation helpers for the Codex surfaces. Nothing here fetches or
   decides what is visible: every value is derived from data the server has
   already bounded to the reader's chapter ceiling. */
import { fmtChapter } from "../../lib/utils.js";

const TYPE_PORTRAIT = {
  character: "PORTRAIT", location: "PLACE", faction: "EMBLEM",
  item: "OBJECT", concept: "CONCEPT", organization: "EMBLEM",
};

export function portraitLabel(type, name) {
  const portrait = TYPE_PORTRAIT[type] || "ENTRY";
  return name ? `${portrait} — ${name}` : portrait;
}

export function buildCiteMap(citations) {
  const map = {};
  (citations || []).forEach((citation) => {
    const kind = (citation.kind || "").toLowerCase();
    map[`${kind}:${citation.id}`] = {
      ch: citation.chapter,
      quote: citation.snippet || "",
      chunk: `${kind} ${citation.id}`,
      label: `${kind.charAt(0).toUpperCase()}${kind.slice(1)} ${citation.id}`,
      kind,
      id: citation.id,
    };
  });
  return map;
}

/* 0..1 position of `value` between `lo` and `hi` (safe for equal bounds). */
export function fraction(value, lo, hi) {
  const span = Number(hi) - Number(lo);
  if (!Number.isFinite(span) || span <= 0) return 1;
  return Math.min(1, Math.max(0, (Number(value) - Number(lo)) / span));
}

/* Tide-staff ticks for the ceiling gauge: evenly spaced marks, labelled with
   the first and last available chapter. */
export function gaugeTicks(min, max, count = 24) {
  const lo = Number(min), hi = Number(max);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return [];
  const ticks = [];
  for (let i = 0; i <= count; i++) {
    const at = i / count;
    const major = i % (count / 4) === 0;
    ticks.push({ at, major, key: i, label: i === 0 ? fmtChapter(lo) : i === count ? fmtChapter(hi) : null });
  }
  return ticks;
}

/* Facts grouped under their chapter, chapters ascending, source order kept
   within a chapter — the "what's known" tideline. */
export function groupFactsByChapter(facts) {
  const groups = new Map();
  (facts || []).forEach((fact) => {
    const key = fact.ch == null ? "?" : String(fact.ch);
    if (!groups.has(key)) groups.set(key, { ch: fact.ch, items: [] });
    groups.get(key).items.push(fact);
  });
  return [...groups.values()].sort((a, b) => {
    if (a.ch == null) return 1;
    if (b.ch == null) return -1;
    return Number(a.ch) - Number(b.ch);
  });
}

/* Radial layout for the relationship constellation, built only from the
   relationships the server returned. One node per related entity (the first
   relation wins its label); capped so labels stay legible. */
export function constellation(relItems, { max = 10, radius = 104 } = {}) {
  const seen = new Map();
  (relItems || []).forEach((rel) => {
    const key = rel.withId != null ? `id:${rel.withId}` : `name:${rel.withName || rel.id}`;
    if (!seen.has(key)) seen.set(key, { ...rel, relations: [rel.type].filter(Boolean) });
    else if (rel.type && !seen.get(key).relations.includes(rel.type)) seen.get(key).relations.push(rel.type);
  });
  const nodes = [...seen.values()].slice(0, max);
  const count = nodes.length;
  const start = count === 2 ? 0 : -Math.PI / 2;
  return {
    total: seen.size,
    nodes: nodes.map((node, index) => {
      const angle = start + (index / Math.max(count, 1)) * Math.PI * 2;
      const x = Math.cos(angle) * radius;
      const y = Math.sin(angle) * radius;
      const side = Math.abs(x) < 18 ? "middle" : x > 0 ? "start" : "end";
      return { ...node, index, angle, x, y, side };
    }),
  };
}

/* Monograms skip a leading article: "The Archivist" → A, not T. */
export function monogramName(name) {
  const value = String(name || "").trim();
  const stripped = value.replace(/^(the|a|an)\s+/i, "");
  return stripped || value;
}

export function truncate(text, max = 16) {
  const value = String(text || "");
  return value.length > max ? `${value.slice(0, max - 1).trimEnd()}…` : value;
}

/* "Built through Ch. 118 of 240 · 118 chapters" — operational build
   coverage, deliberately independent of the reader's spoiler ceiling. */
export function coverageLabel(stats, bookMax) {
  if (stats == null) return "Checking build coverage…";
  const builtThrough = stats.built_through_chapter;
  if (builtThrough == null) return "Codex not built yet";
  const builtCount = Number(stats.built_chapter_count || 0);
  const bookExtent = bookMax != null ? ` of ${fmtChapter(bookMax)}` : "";
  const builtCountLabel = builtCount ? ` · ${builtCount} chapter${builtCount === 1 ? "" : "s"}` : "";
  return `Built through Ch. ${fmtChapter(builtThrough)}${bookExtent}${builtCountLabel}`;
}
