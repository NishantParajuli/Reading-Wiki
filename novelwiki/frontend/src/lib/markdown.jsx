/* ============================================================
   Markdown / answer rendering with inline provenance citations.
   The backend answers + synthesized codex entries are markdown with inline
   tokens like "[Chunk 12, Chapter 5]" / "[Fact 29]". We render:
   - mode "answer": tokens present in citeMap become numbered citation
       buttons that open a source popover; tokens NOT in the map were dropped
       by the server as beyond-ceiling, so we omit them silently (the spoiler
       boundary already did its job server-side).
   - mode "prose": tokens become small, non-clickable chapter markers
       ("ch. 12") when the token or `chapterOf(kind, id)` names a chapter;
       otherwise the internal id means nothing to a reader and the marker is
       dropped. A marker that repeats the one just before it is dropped too.
   ============================================================ */
import React, { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";

/* ---------- Citation popover (context) ---------- */
const CiteContext = createContext({ toggle: () => {}, activeKey: null });

export function CiteProvider({ children }) {
  const [pop, setPop] = useState(null); // { id, cite, n, x, y, top, trigger }
  const popRef = useRef(null);
  popRef.current = pop;
  const panelRef = useRef(null);

  const close = useCallback((restoreFocus = false) => {
    const current = popRef.current;
    setPop(null);
    if (restoreFocus && current && current.trigger && current.trigger.isConnected) current.trigger.focus({ preventScroll: true });
  }, []);

  const toggle = useCallback((next) => {
    setPop(current => (current && current.id === next.id ? null : next));
  }, []);

  useEffect(() => {
    if (!pop) return undefined;
    let frame = 0;
    // Follow the citation while the page scrolls; close once it leaves the view.
    const follow = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const trigger = popRef.current && popRef.current.trigger;
        if (!trigger || !trigger.isConnected) { close(false); return; }
        const r = trigger.getBoundingClientRect();
        if (r.bottom < 0 || r.top > window.innerHeight) { close(false); return; }
        setPop(current => (current && current.trigger === trigger ? { ...current, x: r.left, y: r.bottom, top: r.top } : current));
      });
    };
    const onKey = (e) => { if (e.key === "Escape") close(true); };
    const onDown = (e) => {
      const target = e.target;
      if (panelRef.current && panelRef.current.contains(target)) return;
      if (pop.trigger && pop.trigger.contains(target)) return;
      close(false);
    };
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown, true);
    };
  }, [pop && pop.id, close]); // eslint-disable-line react-hooks/exhaustive-deps

  const value = useMemo(() => ({ toggle, activeKey: pop ? pop.id : null }), [toggle, pop]);
  return (
    <CiteContext.Provider value={value}>
      {children}
      {pop && <CitePopover key={pop.id} cite={pop.cite} n={pop.n} x={pop.x} y={pop.y} top={pop.top} trigger={pop.trigger} panelRef={panelRef} onClose={close} />}
    </CiteContext.Provider>
  );
}

function CitePopover({ cite, n, x, y, top, trigger, panelRef, onClose }) {
  const [pos, setPos] = useState({ left: x, top: y + 12, vis: false, below: true });
  useLayoutEffect(() => {
    const el = panelRef.current; if (!el) return;
    const r = el.getBoundingClientRect();
    const gutter = 12;
    const width = r.width || 320;
    let left = Math.min(x - 18, window.innerWidth - width - gutter);
    left = Math.max(gutter, left);
    let below = true;
    let nextTop = y + 12;
    if (nextTop + r.height > window.innerHeight - gutter && top - r.height - 12 > gutter) {
      nextTop = top - r.height - 12;
      below = false;
    }
    setPos({ left, top: nextTop, vis: true, below });
  }, [x, y, top, panelRef]);
  useEffect(() => {
    if (pos.vis && panelRef.current) panelRef.current.focus({ preventScroll: true });
  }, [pos.vis, panelRef]);
  const kind = cite.kind ? cite.kind.charAt(0).toUpperCase() + cite.kind.slice(1) : "Source";
  return (
    <div ref={panelRef} className={"cite-pop cx-cite-pop" + (pos.below ? "" : " is-above")} role="dialog"
         aria-label={`Source ${n}`} tabIndex={-1}
         style={{ left: pos.left, top: pos.top, visibility: pos.vis ? "visible" : "hidden" }}
         onBlur={(e) => {
           // Keyboard focus leaving for another control closes it; pointer
           // dismissal is handled by the document listener above.
           const to = e.relatedTarget;
           if (!to || e.currentTarget.contains(to) || (trigger && trigger.contains(to))) return;
           onClose(false);
         }}
         onClick={(e) => e.stopPropagation()}>
      <div className="cp-head">
        <span className="cx-cite-num" aria-hidden="true">{n}</span>
        <span className="cp-where">
          <b>{cite.ch != null ? `Chapter ${cite.ch}` : "Source"}</b>
          <span>{kind}{cite.id != null ? ` ${cite.id}` : ""}</span>
        </span>
        <button type="button" className="icon-btn plain cx-cite-close" aria-label="Close source" onClick={() => onClose(true)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
        </button>
      </div>
      {cite.quote
        ? <blockquote className={"cp-quote" + (/^[\u201C\u2018"']/.test(String(cite.quote).trim()) ? " is-quoted" : "")}>{cite.quote}</blockquote>
        : <div className="cp-quote is-empty">Retrieved evidence (bounded)</div>}
      <div className="cp-meta">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4" /></svg>
        <span>Retrieved within your chapter boundary</span>
      </div>
    </div>
  );
}

export function Cite({ n, cite }) {
  const { toggle, activeKey } = useContext(CiteContext);
  const key = useId();
  const expanded = activeKey === key;
  return (
    <button type="button" className={"cite cx-cite" + (expanded ? " is-open" : "")}
            aria-label={`Source ${n}${cite.ch != null ? `, chapter ${cite.ch}` : ""}`}
            aria-haspopup="dialog" aria-expanded={expanded}
            onClick={(e) => {
              e.stopPropagation();
              const r = e.currentTarget.getBoundingClientRect();
              toggle({ id: key, cite, n, x: r.left, y: r.bottom, top: r.top, trigger: e.currentTarget });
            }}>
      {n}
    </button>
  );
}

/* ---------- Markdown parsing ---------- */
// Two citation shapes the models produce: keyword-first `[Chunk 14, Chapter 5]`
// (group 1 = kind, 2 = id) and chapter-first `[Ch.1, id 3]` (group 3 = id, kind
// defaults to chunk since digests are chunk-keyed). Other brackets are left as text.
const _CITE_RE = /\[(?:(chunk|fact|rel|relationship|event)s?\s+(\d+)|[^\]]*?\bid\s*(\d+))[^\]]*\]/gi;
const _CITE_CH_RE = /\b(?:chapter|ch)\.?\s*(\d+(?:\.\d+)?)/i;
const _INLINE_RE = /(\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*|_([^_]+)_)/g;

/* The chapter a prose citation points at: named in the token, else resolved. */
function citeChapter(token, kind, id, chapterOf) {
  const named = _CITE_CH_RE.exec(token);
  if (named) return named[1];
  const resolved = chapterOf ? chapterOf(kind, id) : null;
  return resolved == null || resolved === "" ? null : String(resolved);
}

function StaticCite({ chapter }) {
  return (
    <sup className="cite static" title={`Chapter ${chapter}`}>
      <span aria-hidden="true">ch. {chapter}</span>
      <span className="sr-only"> (chapter {chapter})</span>
    </sup>
  );
}

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
  const { mode = "prose", citeMap = {}, state, chapterOf } = opts || {};
  const out = [];
  let last = 0, m, i = 0;
  let prev = null;   // the last prose marker: { chapter, end }
  _CITE_RE.lastIndex = 0;
  while ((m = _CITE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(...renderInline(text.slice(last, m.index), `${keyBase}-t${i}`));
    let kind = (m[1] || "chunk").toLowerCase();
    if (kind === "relationship") kind = "rel";
    const rid = m[2] || m[3];
    const key = `${kind}:${rid}`;
    const end = m.index + m[0].length;
    if (mode === "answer") {
      const cite = citeMap[key];
      if (cite) {
        let num = state.assigned[key];
        if (!num) { num = ++state.n; state.assigned[key] = num; }
        out.push(<Cite key={`${keyBase}-c${i}`} n={num} cite={cite} />);
      } // else: dropped beyond ceiling → omit token entirely
    } else {
      const chapter = citeChapter(m[0], kind, rid, chapterOf);
      const repeat = prev && prev.chapter === chapter && !text.slice(prev.end, m.index).trim();
      if (chapter != null && !repeat) {
        out.push(<StaticCite key={`${keyBase}-c${i}`} chapter={chapter} />);
      } else if (typeof out[out.length - 1] === "string" && /^[\s.,;:!?)\]]*$/.test(text.slice(end, end + 1))) {
        // Nothing shown: don't leave a stray space before the punctuation.
        out[out.length - 1] = out[out.length - 1].replace(/\s+$/, "");
      }
      if (chapter != null) prev = { chapter, end };
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

// Synthesized prose (codex entry): non-clickable chapter markers. `chapterOf(kind, id)`
// resolves tokens that don't name their chapter (e.g. "[Fact 29]") from known records.
export function Markdown({ text, className = "prose", chapterOf }) {
  return <div className={className}>{renderMarkdown(text, { mode: "prose", chapterOf })}</div>;
}

// Cited answer body: clickable, numbered citations from the /ask citations array.
export function AnswerBody({ answer, citeMap }) {
  const state = { n: 0, assigned: {} };
  const nodes = renderMarkdown(answer, { mode: "answer", citeMap: citeMap || {}, state });
  return <div className="answer-body" data-cites={state.n}>{nodes}</div>;
}

/* The citations an answer actually shows, in the order AnswerBody numbers
   them ({ n, key, cite }). Parses exactly as AnswerBody renders. */
export function collectCitations(answer, citeMap) {
  const state = { n: 0, assigned: {} };
  renderMarkdown(answer, { mode: "answer", citeMap: citeMap || {}, state });
  return Object.entries(state.assigned)
    .map(([key, n]) => ({ n, key, cite: (citeMap || {})[key] }))
    .sort((a, b) => a.n - b.n);
}
