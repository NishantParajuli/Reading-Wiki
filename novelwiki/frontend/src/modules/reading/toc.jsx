/* ============================================================
   Table of contents — volume grouping, chapter rows with read-state /
   new-dot / audio markers. Shared by the novel Chapters tab and the
   reader's TOC drawer. Flat lists virtualize above 200 rows.
   ============================================================ */
import React, { useEffect, useMemo, useState } from "react";
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

export const TOC_ROW_HEIGHT = 44;

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
  return (
    <button
      className={"toc-row" + (isCurrent ? " current" : "") + (isSection ? " toc-section" : "") + (isRead ? " read" : "")}
      style={style}
      onClick={() => onOpen(ch.number)}>
      <span className="toc-num">{isSection ? "—" : ch.number}</span>
      <span className="toc-title">{ch.title || `Chapter ${ch.number}`}</span>
      {isCurrent && <Icon name="play" size={12} className="muted" />}
      {isRead && <Icon name="check" size={13} className="muted" />}
      {isNew && <span className="toc-new-dot" title="Unread" />}
      {isSection && <Chip title="Non-chapter section" className="toc-kind">{TOC_KIND_LABEL[ch.kind] || ch.kind}</Chip>}
      {(!ch.has_content && ch.translation_status === "pending") && <Chip title="Raw — translates on open">raw</Chip>}
      {narrated && <Icon name="headphones" size={14} className="toc-audio" title={audioTitle} />}
    </button>
  );
}

/* Collapsible, volume-grouped TOC. Volumes start collapsed except the one
   holding the current chapter; loose runs above 200 rows are windowed. */
export function VolumeTOC({ toc, currentNumber, maxRead, onOpen, audioCoverage, voices, preferredVoice, sortDesc, virtualize = true, scrollToCurrent = false }) {
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
  const [open, setOpen] = useState({});
  const [expandAll, setExpandAll] = useState(false);
  useEffect(() => { if (currentVol) setOpen(o => (o[currentVol] ? o : { ...o, [currentVol]: true })); }, [currentVol]);

  const rowProps = { currentNumber, maxRead, onOpen, audioByChapter, voiceMap, preferredVoice };

  // Pure flat list (no volumes): window it when long.
  const allLoose = nodes.every(n => n.type === "loose");
  if (allLoose && virtualize && ordered.length > 200) {
    const idx = scrollToCurrent && currentNumber != null
      ? ordered.findIndex(c => c.number === currentNumber)
      : null;
    return (
      <VirtualList
        items={ordered}
        rowHeight={TOC_ROW_HEIGHT}
        scrollToIndex={idx != null && idx >= 0 ? idx : null}
        renderRow={(ch) => (
          <TocRow key={ch.number} ch={ch} {...rowProps} style={{ height: TOC_ROW_HEIGHT }} />
        )}
      />
    );
  }

  const toggle = (label) => setOpen(o => ({ ...o, [label]: !o[label] }));

  return (
    <>
      {nodes.some(n => n.type === "vol") && (
        <div className="row" style={{ justifyContent: "flex-end", padding: "4px 8px" }}>
          <button className="linkish" onClick={() => {
            const next = !expandAll;
            setExpandAll(next);
            const all = {};
            nodes.forEach(n => { if (n.type === "vol") all[n.label] = next; });
            setOpen(all);
          }}>{expandAll ? "Collapse all" : "Expand all"}</button>
        </div>
      )}
      {nodes.map((node, i) => {
        if (node.type === "loose") {
          return <TocRow key={"l" + node.chapter.number} ch={node.chapter} {...rowProps} />;
        }
        const isOpen = !!open[node.label];
        const chapterCount = node.chapters.filter(c => !c.kind || c.kind === "chapter").length;
        const hasCurrent = node.chapters.some(c => c.number === currentNumber);
        return (
          <div key={"v" + i} className={"toc-vol" + (isOpen ? " open" : "")}>
            <button className={"toc-vol-head" + (hasCurrent ? " has-current" : "")}
                    onClick={() => toggle(node.label)} aria-expanded={isOpen}>
              <Icon name="chevronDown" size={16} className="toc-vol-caret" />
              <span className="toc-vol-label">{node.label}</span>
              {hasCurrent && <Chip tone="accent" title="You're reading here">reading</Chip>}
              <span className="toc-vol-count">{chapterCount}</span>
            </button>
            {isOpen && (
              <div className="toc-vol-body">
                {node.chapters.map(ch => <TocRow key={ch.number} ch={ch} {...rowProps} />)}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
