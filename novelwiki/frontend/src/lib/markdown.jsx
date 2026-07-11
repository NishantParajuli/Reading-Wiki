/* ============================================================
   Markdown / answer rendering with inline provenance citations.
   The backend answers + synthesized codex entries are markdown with inline
   tokens like "[Chunk 12, Chapter 5]" / "[Fact 29]". We render:
   - mode "answer": tokens present in citeMap become clickable, numbered <Cite>;
       tokens NOT in the map were dropped by the server as beyond-ceiling, so we
       omit them silently (the spoiler boundary already did its job server-side).
   - mode "prose": tokens render as small, non-clickable footnote markers.
   ============================================================ */
import React, { createContext, useContext, useEffect, useRef, useState } from "react";

/* ---------- Citation popover (context) ---------- */
const CiteContext = createContext({ setPop: () => {} });

export function CiteProvider({ children }) {
  const [pop, setPop] = useState(null); // {cite, x, y}
  useEffect(() => {
    const close = () => setPop(null);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => { window.removeEventListener("scroll", close, true); window.removeEventListener("resize", close); };
  }, []);
  return (
    <CiteContext.Provider value={{ setPop }}>
      {children}
      {pop && <CitePopover {...pop} onClose={() => setPop(null)} />}
    </CiteContext.Provider>
  );
}

function CitePopover({ cite, x, y }) {
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
  return (
    <div ref={ref} className="cite-pop" style={{ left: pos.left, top: pos.top, visibility: pos.vis ? "visible" : "hidden" }}
         onClick={(e) => e.stopPropagation()}>
      <div className="cp-head">
        <span className="chip mono">ch. {cite.ch}</span>
        <span className="muted" style={{ fontSize: "var(--text-xs)" }}>{cite.label || ""}</span>
      </div>
      {cite.quote
        ? <div className="cp-quote">“{cite.quote}”</div>
        : <div className="cp-quote muted">Retrieved evidence (bounded)</div>}
      <div className="cp-meta">
        <span>{cite.chunk || ""}</span>
        <span>retrieved · bounded</span>
      </div>
    </div>
  );
}

export function Cite({ n, cite }) {
  const { setPop } = useContext(CiteContext);
  return (
    <sup className="cite" onClick={(e) => {
      e.stopPropagation();
      const r = e.currentTarget.getBoundingClientRect();
      setPop({ cite, x: r.left, y: r.bottom });
    }}>{n}</sup>
  );
}

/* ---------- Markdown parsing ---------- */
// Two citation shapes the models produce: keyword-first `[Chunk 14, Chapter 5]`
// (group 1 = kind, 2 = id) and chapter-first `[Ch.1, id 3]` (group 3 = id, kind
// defaults to chunk since digests are chunk-keyed). Other brackets are left as text.
const _CITE_RE = /\[(?:(chunk|fact|rel|relationship|event)s?\s+(\d+)|[^\]]*?\bid\s*(\d+))[^\]]*\]/gi;
const _INLINE_RE = /(\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*|_([^_]+)_)/g;

function renderInline(text, keyBase) {
  if (!text) return [];
  const out = [];
  let last = 0, m, i = 0;
  _INLINE_RE.lastIndex = 0;
  while ((m = _INLINE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${keyBase}-i${i++}`;
    if (m[2] != null) out.push(<strong key={k}>{m[2]}</strong>);
    else if (m[3] != null) out.push(<code key={k}>{m[3]}</code>);
    else if (m[4] != null) out.push(<em key={k}>{m[4]}</em>);
    else if (m[5] != null) out.push(<em key={k}>{m[5]}</em>);
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
    let kind = (m[1] || "chunk").toLowerCase();
    if (kind === "relationship") kind = "rel";
    const rid = m[2] || m[3];
    const key = `${kind}:${rid}`;
    if (mode === "answer") {
      const cite = citeMap[key];
      if (cite) {
        let num = state.assigned[key];
        if (!num) { num = ++state.n; state.assigned[key] = num; }
        out.push(<Cite key={`${keyBase}-c${i}`} n={num} cite={cite} />);
      } // else: dropped beyond ceiling → omit token entirely
    } else {
      out.push(<sup key={`${keyBase}-c${i}`} className="cite static" title={`${kind} ${rid}`}>{rid}</sup>);
    }
    i++;
    last = _CITE_RE.lastIndex;
  }
  if (last < text.length) out.push(...renderInline(text.slice(last), `${keyBase}-t${i}`));
  return out;
}

// Block-level markdown → React nodes. Deliberately small: paragraphs, #/##/###
// headings, - / * and 1. lists, > blockquotes. No tables/images/raw HTML.
export function renderMarkdown(md, opts) {
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
      const Tag = "h" + heading[1].length;
      nodes.push(<Tag key={`b${bi}`}>{renderSegment(heading[2], opts, `b${bi}`)}</Tag>);
    } else if (isUl || isOl) {
      const Tag = isOl ? "ol" : "ul";
      nodes.push(
        <Tag key={`b${bi}`}>
          {lines.map((l, li) => (
            <li key={`b${bi}l${li}`}>{renderSegment(l.replace(/^\s*(?:[-*]|\d+\.)\s+/, ""), opts, `b${bi}l${li}`)}</li>
          ))}
        </Tag>
      );
    } else if (isQuote) {
      const inner = lines.map(l => l.replace(/^\s*>\s?/, "")).join(" ");
      nodes.push(<blockquote key={`b${bi}`}>{renderSegment(inner, opts, `b${bi}`)}</blockquote>);
    } else {
      nodes.push(<p key={`b${bi}`}>{renderSegment(lines.join(" "), opts, `b${bi}`)}</p>);
    }
  });
  return nodes;
}

// Synthesized prose (codex entry): non-clickable footnote markers.
export function Markdown({ text, className = "prose" }) {
  return <div className={className}>{renderMarkdown(text, { mode: "prose" })}</div>;
}

// Cited answer body: clickable, numbered citations from the /ask citations array.
export function AnswerBody({ answer, citeMap }) {
  const state = { n: 0, assigned: {} };
  const nodes = renderMarkdown(answer, { mode: "answer", citeMap: citeMap || {}, state });
  return <div className="answer-body" data-cites={state.n}>{nodes}</div>;
}
