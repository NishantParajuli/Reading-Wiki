/* ============================================================
   Shared UI primitives → window
   ============================================================ */
const { useState, useEffect, useRef, useMemo, useCallback, createContext, useContext } = React;

/* ---------- Icons (simple line set) ---------- */
const PATHS = {
  book: "M4 5a2 2 0 0 1 2-2h11v16H6a2 2 0 0 0-2 2zM17 3v18",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  sparkles: "M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4zM19 14l.9 2.3L22 17l-2.1.7L19 20l-.9-2.3L16 17l2.1-.7z",
  lock: "M6 10V8a6 6 0 0 1 12 0v2M5 10h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z",
  unlock: "M7 10V8a5 5 0 0 1 9.5-2M5 10h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z",
  sun: "M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  mapPin: "M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  users: "M9 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M17 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-5-6.7",
  gem: "M6 3h12l3 6-9 12L3 9zM3 9h18M9 3 6 9l6 12M15 3l3 6-6 12",
  spark: "M12 2v6M12 16v6M2 12h6M16 12h6M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3",
  arrowRight: "M5 12h14M13 6l6 6-6 6",
  arrowLeft: "M19 12H5M11 18l-6-6 6-6",
  link: "M9 15l6-6M10 6l1-1a4 4 0 0 1 6 6l-1 1M14 18l-1 1a4 4 0 0 1-6-6l1-1",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  quote: "M7 7H4a1 1 0 0 0-1 1v4a1 1 0 0 0 1 1h3v3a3 3 0 0 1-3 3M20 7h-3a1 1 0 0 0-1 1v4a1 1 0 0 0 1 1h3v3a3 3 0 0 1-3 3",
  x: "M18 6 6 18M6 6l12 12",
  check: "M20 6 9 17l-5-5",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4",
  brain: "M9 3a3 3 0 0 0-3 3 3 3 0 0 0-1 5.8A3 3 0 0 0 6 17a3 3 0 0 0 3 3V3zM15 3a3 3 0 0 1 3 3 3 3 0 0 1 1 5.8A3 3 0 0 1 18 17a3 3 0 0 1-3 3V3z",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5M3 17l9 5 9-5",
  compass: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM15.5 8.5l-2 5-5 2 2-5z",
  send: "M22 2 11 13M22 2l-7 20-4-9-9-4z",
  sliders: "M4 6h11M19 6h1M4 12h1M9 12h11M4 18h7M15 18h5M15 4v4M5 10v4M11 16v4",
  filter: "M3 5h18l-7 8v6l-4-2v-4z",
  chevronDown: "M6 9l6 6 6-6",
  spider: "M12 8a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M4 7l3 2M17 15l3 2M4 17l3-2M17 9l3-2M2 12h3M19 12h3",
  scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.1 8.1 20 20M8.1 15.9 20 4",
  cpu: "M9 3v2M15 3v2M9 19v2M15 19v2M3 9h2M3 15h2M19 9h2M19 15h2M6 6h12v12H6zM10 10h4v4h-4z",
  merge: "M7 3v6a4 4 0 0 0 4 4h6M7 3l-3 3M7 3l3 3M17 13l3-3M17 13l-3-3",
  refresh: "M21 12a9 9 0 1 1-3-6.7M21 4v4h-4",
  database: "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
};
function Icon({ name, size = 18, sw = 1.7, className = "", style }) {
  const d = PATHS[name] || "";
  return React.createElement("svg", {
    width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: sw, strokeLinecap: "round", strokeLinejoin: "round",
    className, style, "aria-hidden": true,
  }, d.split("M").filter(Boolean).map((seg, i) =>
    React.createElement("path", { key: i, d: "M" + seg })
  ));
}

const TYPE_ICON = { character: "user", location: "mapPin", faction: "users", item: "gem", concept: "spark", organization: "users" };
const TYPE_LABEL = { character: "Character", location: "Location", faction: "Faction", item: "Item", concept: "Concept", organization: "Org" };

/* ---------- Placeholder avatar ---------- */
function Avatar({ entity, lg, locked }) {
  return React.createElement("div", { className: `avatar ${lg ? "lg" : ""} t-${entity.type}` },
    React.createElement("div", { className: "ph" },
      React.createElement("div", { className: "ph-label" }, locked ? "—" : entity.portrait)
    )
  );
}

/* ---------- Type badge ---------- */
function TypeBadge({ type }) {
  return React.createElement("span", { className: `badge t-${type}` },
    React.createElement(Icon, { name: TYPE_ICON[type] || "spark", size: 12, sw: 2 }),
    TYPE_LABEL[type] || type
  );
}

/* ---------- Reveal wrapper ----------
   Shows children when ceiling >= chapter, else a redacted cover.
   Animates on cross because the node persists and classes toggle. */
function Reveal({ chapter, ceiling, lines = 2, label, children, className = "" }) {
  const locked = ceiling < chapter;
  const lockLabel = label || `Unlocks at ch. ${chapter}`;
  return React.createElement("div", { className: `reveal ${locked ? "locked" : ""} ${className}` },
    React.createElement("div", { className: "r-content", "aria-hidden": locked }, children),
    React.createElement("div", { className: "r-cover" },
      React.createElement("div", { className: "redact" },
        Array.from({ length: lines }).map((_, i) =>
          React.createElement("span", { key: i, style: { width: i === lines - 1 ? "62%" : "100%" } })
        )
      ),
      React.createElement("span", { className: "lock-pill" },
        React.createElement(Icon, { name: "lock", size: 12, className: "lk" }), lockLabel
      )
    )
  );
}

/* ---------- Loading + empty helpers ---------- */
function Loading({ label = "Loading…" }) {
  return React.createElement("div", { className: "loading-row" },
    React.createElement("div", { className: "spinner" }), label
  );
}
function SkeletonGrid({ count = 6 }) {
  return React.createElement("div", { className: "skeleton-grid" },
    Array.from({ length: count }).map((_, i) =>
      React.createElement("div", { key: i, className: "ecard skeleton t-concept" },
        React.createElement("div", { className: "ecard-top" },
          React.createElement("div", { className: "avatar t-concept" }),
          React.createElement("div", { className: "redact", style: { maxWidth: 130 } },
            React.createElement("span", { style: { width: "80%", height: 13 } }))
        ),
        React.createElement("div", { className: "redact" },
          React.createElement("span", { style: { width: "100%" } }),
          React.createElement("span", { style: { width: "55%" } }))
      )
    )
  );
}
function EmptyState({ icon = "search", title, body }) {
  return React.createElement("div", { className: "notfound" },
    React.createElement(Icon, { name: icon, size: 20, className: "muted" }),
    React.createElement("div", null,
      React.createElement("b", null, title),
      body && React.createElement("div", { className: "muted", style: { fontSize: 14, marginTop: 2 } }, body)
    )
  );
}

/* ---------- useDebounce ---------- */
function useDebounce(value, ms = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/* ---------- Citation popover (global) ---------- */
const CiteContext = createContext(null);
function CiteProvider({ children }) {
  const [pop, setPop] = useState(null); // {cite, x, y}
  useEffect(() => {
    const close = () => setPop(null);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => { window.removeEventListener("scroll", close, true); window.removeEventListener("resize", close); };
  }, []);
  return React.createElement(CiteContext.Provider, { value: { setPop } },
    children,
    pop && React.createElement(CitePopover, { ...pop, onClose: () => setPop(null) })
  );
}
function CitePopover({ cite, x, y, onClose }) {
  const ref = useRef(null);
  const [pos, setPos] = useState({ left: x, top: y, vis: false });
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const w = 300, r = el.getBoundingClientRect();
    let left = Math.min(x, window.innerWidth - w - 14);
    left = Math.max(14, left);
    let top = y + 14;
    if (top + r.height > window.innerHeight - 14) top = y - r.height - 14;
    setPos({ left, top, vis: true });
  }, [x, y]);
  // Real citations carry no entity object; fall back to the kind/id label.
  const ent = (window.NOVEL && window.NOVEL.entities || []).find(e => e.id === cite.entity);
  return React.createElement("div", {
    ref, className: "cite-pop",
    style: { left: pos.left, top: pos.top, visibility: pos.vis ? "visible" : "hidden" },
    onClick: (e) => e.stopPropagation(),
  },
    React.createElement("div", { className: "cp-head" },
      React.createElement("span", { className: "chip mono" }, `ch. ${cite.ch}`),
      React.createElement("span", { className: "muted", style: { fontSize: 12.5 } }, ent ? ent.name : (cite.label || ""))
    ),
    cite.quote
      ? React.createElement("div", { className: "cp-quote" }, `“${cite.quote}”`)
      : React.createElement("div", { className: "cp-quote muted" }, "Retrieved evidence (bounded)"),
    React.createElement("div", { className: "cp-meta" },
      React.createElement("span", null, cite.chunk || ""),
      React.createElement("span", null, "retrieved · bounded")
    )
  );
}
function Cite({ n, cite }) {
  const { setPop } = useContext(CiteContext);
  return React.createElement("sup", {
    className: "cite",
    onClick: (e) => { e.stopPropagation(); const r = e.currentTarget.getBoundingClientRect(); setPop({ cite, x: r.left, y: r.bottom }); },
  }, n);
}

/* ============================================================
   Markdown / answer rendering
   The backend answers + synthesized codex entries are markdown with inline
   provenance tokens like "[Chunk 12, Chapter 5]" / "[Fact 29]". We render:
   - mode "answer": tokens present in citeMap become clickable, numbered <Cite>;
       tokens NOT in the map were dropped by the server as beyond-ceiling, so we
       omit them silently (the spoiler boundary already did its job server-side).
   - mode "prose": tokens render as small, non-clickable footnote markers.
   ============================================================ */
const _CITE_RE = /\[(chunk|fact|rel|relationship|event)s?\s+(\d+)[^\]]*\]/gi;
const _INLINE_RE = /(\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*|_([^_]+)_)/g;

function renderInline(text, keyBase) {
  if (!text) return [];
  const out = [];
  let last = 0, m, i = 0;
  _INLINE_RE.lastIndex = 0;
  while ((m = _INLINE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${keyBase}-i${i++}`;
    if (m[2] != null) out.push(React.createElement("strong", { key: k }, m[2]));
    else if (m[3] != null) out.push(React.createElement("code", { key: k }, m[3]));
    else if (m[4] != null) out.push(React.createElement("em", { key: k }, m[4]));
    else if (m[5] != null) out.push(React.createElement("em", { key: k }, m[5]));
    last = _INLINE_RE.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function renderSegment(text, opts, keyBase) {
  const { mode = "prose", citeMap = {}, state } = opts || {};
  const out = [];
  let last = 0, m, i = 0;
  _CITE_RE.lastIndex = 0;
  while ((m = _CITE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(...renderInline(text.slice(last, m.index), `${keyBase}-t${i}`));
    let kind = m[1].toLowerCase();
    if (kind === "relationship") kind = "rel";
    const key = `${kind}:${m[2]}`;
    if (mode === "answer") {
      const cite = citeMap[key];
      if (cite) {
        let num = state.assigned[key];
        if (!num) { num = ++state.n; state.assigned[key] = num; }
        out.push(React.createElement(Cite, { key: `${keyBase}-c${i}`, n: num, cite }));
      } // else: dropped beyond ceiling → omit token entirely
    } else {
      out.push(React.createElement("sup", { key: `${keyBase}-c${i}`, className: "cite static", title: `${kind} ${m[2]}` }, m[2]));
    }
    i++;
    last = _CITE_RE.lastIndex;
  }
  if (last < text.length) out.push(...renderInline(text.slice(last), `${keyBase}-t${i}`));
  return out;
}

// Block-level markdown → React nodes. Deliberately small: paragraphs, #/##/###
// headings, - / * and 1. lists, > blockquotes. No tables/images/raw HTML.
function renderMarkdown(md, opts) {
  const text = (md || "").replace(/\r\n/g, "\n").trim();
  if (!text) return [];
  const blocks = text.split(/\n{2,}/);
  const nodes = [];
  blocks.forEach((block, bi) => {
    const lines = block.split("\n");
    const heading = lines[0].match(/^(#{1,3})\s+(.*)$/);
    const isUl = lines.every(l => /^\s*[-*]\s+/.test(l));
    const isOl = lines.every(l => /^\s*\d+\.\s+/.test(l));
    const isQuote = lines.every(l => /^\s*>\s?/.test(l));
    if (heading) {
      const tag = "h" + heading[1].length;
      nodes.push(React.createElement(tag, { key: `b${bi}` }, renderSegment(heading[2], opts, `b${bi}`)));
    } else if (isUl || isOl) {
      const tag = isOl ? "ol" : "ul";
      nodes.push(React.createElement(tag, { key: `b${bi}` },
        lines.map((l, li) => React.createElement("li", { key: `b${bi}l${li}` },
          renderSegment(l.replace(/^\s*(?:[-*]|\d+\.)\s+/, ""), opts, `b${bi}l${li}`)))
      ));
    } else if (isQuote) {
      const inner = lines.map(l => l.replace(/^\s*>\s?/, "")).join(" ");
      nodes.push(React.createElement("blockquote", { key: `b${bi}` }, renderSegment(inner, opts, `b${bi}`)));
    } else {
      nodes.push(React.createElement("p", { key: `b${bi}` }, renderSegment(lines.join(" "), opts, `b${bi}`)));
    }
  });
  return nodes;
}

// Synthesized prose (codex entry): non-clickable footnote markers.
function Markdown({ text, className = "prose" }) {
  return React.createElement("div", { className }, renderMarkdown(text, { mode: "prose" }));
}

// Cited answer body: clickable, numbered citations from the /ask citations array.
function AnswerBody({ answer, citeMap }) {
  const state = { n: 0, assigned: {} };
  const nodes = renderMarkdown(answer, { mode: "answer", citeMap: citeMap || {}, state });
  return React.createElement("div", { className: "answer-body", "data-cites": state.n }, nodes);
}

Object.assign(window, {
  Icon, Avatar, TypeBadge, Reveal, CiteProvider, CiteContext, Cite,
  Loading, SkeletonGrid, EmptyState, useDebounce,
  Markdown, AnswerBody, renderMarkdown,
  TYPE_ICON, TYPE_LABEL,
  useState, useEffect, useRef, useMemo, useCallback, createContext, useContext,
});
