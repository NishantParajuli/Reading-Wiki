/* ============================================================
   Table of contents — volume grouping, chapter rows with read-state /
   new-dot / audio markers. Shared by the novel Chapters tab and the
   reader's contents drawer (which renders it ~360px wide, unvirtualized).
   Flat lists virtualize above 200 rows (fixed TOC_ROW_HEIGHT rows).
   Volumes open with a height tide (grid rows 0fr → 1fr); their rows mount
   only while open, so a 1,400-chapter book stays light.
   ============================================================ */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../../components/Icon.jsx";
import { Chip } from "../../components/ui.jsx";
import { VirtualList } from "../../components/VirtualList.jsx";

// Non-chapter sections from file imports get a short tag instead of a number.
const TOC_KIND_LABEL = { frontmatter: "front", interlude: "interlude", backmatter: "extra" };

export function ttsVoiceLabel(id, voiceMap) {
  const v = voiceMap && voiceMap.get(id);
  if (!v) return id;
  const name = v.name || id;
  return v.id && v.id !== name ? `${name} (${v.id})` : name;
}

export function ttsVoiceMeta(v) {
  return [v && v.language, v && v.gender, v && v.accent].filter(Boolean).join(" · ");
}

/* Group the flat chapter list into ordered TOC nodes: consecutive chapters
   sharing a part_label fold into one collapsible volume. */
export function groupToc(toc) {
  const nodes = [];
  let cur = null;
  toc.forEach(ch => {
    const pl = ch.part_label || null;
    if (pl) {
      if (!cur || cur.label !== pl) { cur = { type: "vol", label: pl, chapters: [] }; nodes.push(cur); }
      cur.chapters.push(ch);
    } else {
      cur = null;
      nodes.push({ type: "loose", chapter: ch });
    }
  });
  return nodes;
}

export const TOC_ROW_HEIGHT = 48;

export function TocRow({ ch, currentNumber, maxRead, onOpen, audioByChapter, voiceMap, preferredVoice, style }) {
  const isSection = ch.kind && ch.kind !== "chapter";
  const voices = (audioByChapter && audioByChapter.get(Number(ch.number))) || [];
  const narrated = voices.length > 0;
  const preferredAvailable = preferredVoice && voices.includes(preferredVoice);
  const audioTitle = narrated
    ? preferredAvailable
      ? `Narrated in preferred voice: ${ttsVoiceLabel(preferredVoice, voiceMap)}`
      : `Narrated in: ${voices.map(v => ttsVoiceLabel(v, voiceMap)).join(", ")}`
    : null;
  const isCurrent = currentNumber === ch.number;
  const isRead = !isCurrent && maxRead != null && ch.number <= maxRead;
  const isNew = maxRead != null && !isSection && ch.number > maxRead;
  const isRaw = !ch.has_content && ch.translation_status === "pending";
  return (
    <button
      type="button"
      className={"toc-row" + (isCurrent ? " current" : "") + (isSection ? " toc-section" : "") + (isRead ? " read" : "") + (isNew ? " new" : "")}
      style={style}
      data-toc-number={ch.number}
      aria-current={isCurrent ? "location" : undefined}
      onClick={() => onOpen(ch.number)}>
      <span className="toc-num">{isSection ? "—" : ch.number}</span>
      <span className="toc-title">{ch.title || `Chapter ${ch.number}`}</span>
      <span className="toc-marks">
        {isCurrent && <span className="toc-here"><span className="toc-here-dot" aria-hidden="true" /><span className="toc-here-text">You are here</span></span>}
        {isSection && <Chip title="Non-chapter section" className="toc-kind">{TOC_KIND_LABEL[ch.kind] || ch.kind}</Chip>}
        {isRaw && <Chip title="Raw — translates on open" className="toc-raw">raw</Chip>}
        {narrated && (
          <span className={"toc-audio" + (preferredAvailable ? " is-preferred" : "")} title={audioTitle} role="img" aria-label={audioTitle}>
            <Icon name="headphones" size={14} />
          </span>
        )}
        {isRead && <span className="toc-read" role="img" aria-label="Read" title="Read"><Icon name="check" size={13} sw={2.2} /></span>}
        {isNew && !isCurrent && <span className="toc-new-dot" role="img" aria-label="Unread" title="Unread" />}
      </span>
    </button>
  );
}

/* Height-tide disclosure: mounts its children while open (or closing),
   animates grid rows 0fr ⇄ 1fr, and is inert while closed. */
function Collapse({ open, id, children }) {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(open);
  const ref = useRef(null);

  useEffect(() => {
    if (open) { setMounted(true); return undefined; }
    setShown(false);
    const t = setTimeout(() => setMounted(false), 460);
    return () => clearTimeout(t);
  }, [open]);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Closed (or closing) content leaves the tab order and the a11y tree.
    if (open) el.removeAttribute("inert"); else el.setAttribute("inert", "");
    if (!open || shown) return;
    void el.offsetHeight;   // commit the collapsed frame, then open
    setShown(true);
  }, [open, mounted, shown]);

  if (!mounted) return null;
  return (
    <div ref={ref} id={id} className={"toc-collapse" + (shown ? " is-open" : "")}>
      <div className="toc-collapse-inner">{children}</div>
    </div>
  );
}

/* The nearest ancestor that really scrolls (the Reader's drawer body), else null
   for the window. Collapse boxes clip with overflow:hidden and are skipped. */
function scrollParent(el) {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY;
    if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

function centerRow(row, smooth) {
  const behavior = smooth ? "smooth" : "auto";
  const r = row.getBoundingClientRect();
  const box = scrollParent(row);
  if (box) {
    const b = box.getBoundingClientRect();
    box.scrollTo({ top: box.scrollTop + (r.top - b.top) - box.clientHeight / 2 + r.height / 2, behavior });
  } else {
    window.scrollTo({ top: Math.max(0, window.scrollY + r.top - window.innerHeight / 2 + r.height / 2), behavior });
  }
}

function splitLabel(label) {
  const m = /^(.{1,28}?)\s*[:：—–-]\s+(.+)$/.exec(label || "");
  return m ? { kicker: m[1], name: m[2] } : { kicker: null, name: label };
}

/* Collapsible, volume-grouped TOC. Volumes start collapsed except the one
   holding the current chapter; loose runs above 200 rows are windowed. */
export function VolumeTOC({ toc, currentNumber, maxRead, onOpen, audioCoverage, voices, preferredVoice, sortDesc, virtualize = true, scrollToCurrent = false, locateNonce = 0 }) {
  const ordered = useMemo(() => (sortDesc ? [...toc].reverse() : toc), [toc, sortDesc]);
  const nodes = useMemo(() => groupToc(ordered), [ordered]);
  const audioByChapter = useMemo(() => {
    const m = new Map();
    ((audioCoverage && audioCoverage.chapters) || []).forEach(row => {
      m.set(Number(row.chapter), row.voices || []);
    });
    return m;
  }, [audioCoverage]);
  const voiceMap = useMemo(() => new Map((voices || []).map(v => [v.id, v])), [voices]);
  const currentVol = useMemo(() => {
    if (currentNumber == null) return null;
    const hit = toc.find(c => c.number === currentNumber);
    return hit ? (hit.part_label || null) : null;
  }, [toc, currentNumber]);
  const [open, setOpen] = useState(() => (currentVol ? { [currentVol]: true } : {}));
  const [expandAll, setExpandAll] = useState(false);
  const idBase = useRef(`toc-${Math.random().toString(36).slice(2, 8)}`).current;
  const listRef = useRef(null);
  useEffect(() => { if (currentVol) setOpen(o => (o[currentVol] ? o : { ...o, [currentVol]: true })); }, [currentVol]);

  // "Locate": open the current chapter's volume and bring its row into view.
  // A volume that has to open first is short while its height tide runs (the
  // page would clamp the scroll), so the glide waits until it has settled.
  useEffect(() => {
    if (!locateNonce || currentNumber == null) return undefined;
    if (currentVol && !open[currentVol]) setOpen(o => ({ ...o, [currentVol]: true }));
    const smooth = !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    const startedAt = Date.now();
    const patient = () => Date.now() - startedAt < 1600;
    let timer = 0;
    const attempt = () => {
      const list = listRef.current;
      if (!list) return;
      const row = list.querySelector('[aria-current="location"]');
      if (row) {
        const box = row.closest(".toc-collapse");
        const inner = box && box.firstElementChild;
        const settled = !box || (box.classList.contains("is-open") && inner
          && Math.abs(box.getBoundingClientRect().height - inner.scrollHeight) < 2);
        if (!settled && patient()) { timer = setTimeout(attempt, 60); return; }
        centerRow(row, smooth);
        row.classList.remove("is-located"); void row.offsetWidth; row.classList.add("is-located");
        row.focus({ preventScroll: true });
        return;
      }
      if (currentVol && patient()) { timer = setTimeout(attempt, 60); return; }   // volume still mounting
      // Flat, windowed list: the row may not be rendered yet — scroll by index.
      const idx = ordered.findIndex(c => c.number === currentNumber);
      const spacer = list.firstElementChild;
      if (idx >= 0 && spacer) {
        const y = spacer.getBoundingClientRect().top + window.scrollY + idx * TOC_ROW_HEIGHT - window.innerHeight / 2 + TOC_ROW_HEIGHT / 2;
        window.scrollTo({ top: Math.max(0, y), behavior: smooth ? "smooth" : "auto" });
      }
    };
    timer = setTimeout(attempt, 30);
    return () => clearTimeout(timer);
  }, [locateNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const rowProps = { currentNumber, maxRead, onOpen, audioByChapter, voiceMap, preferredVoice };

  // Pure flat list (no volumes): window it when long.
  const allLoose = nodes.every(n => n.type === "loose");
  if (allLoose && virtualize && ordered.length > 200) {
    const idx = scrollToCurrent && currentNumber != null
      ? ordered.findIndex(c => c.number === currentNumber)
      : null;
    return (
      <div className="toc-list is-virtual" ref={listRef}>
        <VirtualList
          items={ordered}
          rowHeight={TOC_ROW_HEIGHT}
          scrollToIndex={idx != null && idx >= 0 ? idx : null}
          renderRow={(ch) => (
            <TocRow key={ch.number} ch={ch} {...rowProps} style={{ height: TOC_ROW_HEIGHT }} />
          )}
        />
      </div>
    );
  }

  const toggle = (label) => setOpen(o => ({ ...o, [label]: !o[label] }));
  const hasVolumes = nodes.some(n => n.type === "vol");

  return (
    <div className="toc-list" ref={listRef}>
      {hasVolumes && (
        <div className="toc-list-head">
          <button type="button" className="linkish toc-expand" onClick={() => {
            const next = !expandAll;
            setExpandAll(next);
            const all = {};
            nodes.forEach(n => { if (n.type === "vol") all[n.label] = next; });
            setOpen(all);
          }}>
            <Icon name={expandAll ? "chevronUp" : "chevronDown"} size={13} sw={2} />
            {expandAll ? "Collapse all" : "Expand all"}
          </button>
        </div>
      )}
      {nodes.map((node, i) => {
        if (node.type === "loose") {
          return <TocRow key={"l" + node.chapter.number} ch={node.chapter} {...rowProps} />;
        }
        const isOpen = !!open[node.label];
        const chapters = node.chapters.filter(c => !c.kind || c.kind === "chapter");
        const chapterCount = chapters.length;
        const readCount = maxRead != null ? chapters.filter(c => c.number <= maxRead).length : 0;
        const volPct = chapterCount ? Math.round((readCount / chapterCount) * 100) : 0;
        const hasCurrent = node.chapters.some(c => c.number === currentNumber);
        const { kicker, name } = splitLabel(node.label);
        const bodyId = `${idBase}-v${i}`;
        return (
          <div key={"v" + i} className={"toc-vol" + (isOpen ? " open" : "") + (hasCurrent ? " has-current" : "") + (volPct === 100 ? " is-done" : "")}>
            <button type="button" className={"toc-vol-head" + (hasCurrent ? " has-current" : "")}
                    onClick={() => toggle(node.label)} aria-expanded={isOpen} aria-controls={bodyId}>
              <span className="toc-vol-bg" aria-hidden="true" />
              <span className="toc-vol-caret" aria-hidden="true"><Icon name="chevronDown" size={15} sw={2} /></span>
              <span className="toc-vol-text">
                {kicker && <span className="toc-vol-kicker">{kicker}</span>}
                <span className="toc-vol-label">{name}</span>
              </span>
              {hasCurrent && <span className="toc-vol-here" title="You're reading here">Reading</span>}
              {maxRead != null && readCount > 0 && (
                <span className="toc-vol-meter" role="img" aria-label={`${readCount} of ${chapterCount} read`} title={`${readCount} of ${chapterCount} read`}>
                  <i style={{ width: `${volPct}%` }} />
                </span>
              )}
              <span className="toc-vol-count">{chapterCount}</span>
            </button>
            <Collapse open={isOpen} id={bodyId}>
              <div className="toc-vol-body">
                {node.chapters.map(ch => <TocRow key={ch.number} ch={ch} {...rowProps} />)}
              </div>
            </Collapse>
          </div>
        );
      })}
    </div>
  );
}
