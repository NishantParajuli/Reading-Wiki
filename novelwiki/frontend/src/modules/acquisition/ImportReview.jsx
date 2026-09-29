/* ============================================================
   Review editor — book details, the segment plan, and the sticky glass
   commit bar (new novel / append / replace).
   ============================================================ */
import React, { useEffect, useId, useRef, useState } from "react";

import { catalogApi } from "../catalog/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip } from "../../components/ui.jsx";
import { motion, springs } from "../../motion/index.js";
import { IMPORT_KIND_LABEL, IMPORT_KINDS } from "./importStatus.js";

const MODES = [
  { id: "new", label: "New novel" },
  { id: "append", label: "Append to…" },
  { id: "replace", label: "Replace…", title: "Overwrite an existing source's chapters" },
];

export function SegmentRow({ seg, onPatch, onMerge, onSplit, canMerge, index, flash }) {
  const name = seg.title || "untitled segment";
  const wc = seg.word_count != null ? `${seg.word_count.toLocaleString()} words` : "";
  const missing = seg.include && seg.kind === "chapter" && seg.number == null;
  const range = seg.block_range || [0, 0];
  const cls = ["imp-seg", `kind-${seg.kind}`, seg.include ? "" : "is-excluded", flash ? "is-flash" : ""].filter(Boolean).join(" ");
  return (
    <div className={cls} data-seg-index={index} style={index != null ? { "--i": Math.min(index, 14) } : undefined}>
      <label className="check imp-seg-include" title={seg.include ? "Included" : "Excluded"}>
        <input type="checkbox" aria-label={`Include ${name}`} checked={!!seg.include} onChange={e => onPatch({ include: e.target.checked })} />
      </label>
      <div className="imp-seg-main">
        <div className="imp-seg-line1">
          {index != null && <span className="imp-seg-idx" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>}
          <input className="imp-seg-title" value={seg.title || ""} aria-label="Segment title"
                 onChange={e => onPatch({ title: e.target.value })} placeholder="Untitled" />
          <select className="imp-seg-kind" aria-label={`Type of ${name}`} value={seg.kind} onChange={e => onPatch({ kind: e.target.value })}>
            {IMPORT_KINDS.map(k => <option key={k} value={k}>{IMPORT_KIND_LABEL[k] || k}</option>)}
          </select>
          <label className={"imp-seg-num" + (missing ? " is-missing" : "")} title={missing ? "This chapter has no number yet" : "Chapter number"}>
            <span aria-hidden="true">#</span>
            <input value={seg.number == null ? "" : seg.number} placeholder="–"
                   aria-label={`Chapter number for ${name}`} type="number" step="any" inputMode="decimal"
                   onChange={e => { const v = e.target.value.trim(); onPatch({ number: v === "" ? null : Number(v) }); }} />
          </label>
        </div>
        <div className="imp-seg-line2">
          <input className="imp-seg-vol" value={seg.part_label || ""}
                 aria-label={`Volume/group for ${name}`}
                 onChange={e => onPatch({ part_label: e.target.value || null })}
                 placeholder="Volume/group" />
          <span className="imp-seg-range" title="Source block range">{range[0]}–{range[1]}</span>
          {wc && <span className="imp-seg-words">{wc}</span>}
          {seg.first_line && <span className="imp-seg-first">{seg.first_line}</span>}
        </div>
      </div>
      <div className="imp-seg-actions">
        <button type="button" className="icon-btn plain imp-seg-merge" title="Merge into previous" aria-label="Merge into previous" disabled={!canMerge} onClick={onMerge}>
          <Icon name="merge" size={15} />
        </button>
        <button type="button" className="icon-btn plain imp-seg-split" title="Split in half" aria-label="Split in half" onClick={onSplit}>
          <Icon name="scissors" size={15} />
        </button>
      </div>
    </div>
  );
}

/* Stable per-row keys: segments partition the block stream, so the first
   block identifies a row across merges and splits (index breaks ties). */
function rowKeys(segments) {
  const seen = new Set();
  return segments.map((s, i) => {
    let key = `${s.id}:${s.block_range ? s.block_range[0] : i}`;
    if (seen.has(key)) key += `:${i}`;
    seen.add(key);
    return key;
  });
}

export function PlanEditor({
  job, plan, setPlan, metadata, setMetadata, onSave, onCommit, busy,
}) {
  const segs = plan.segments || [];
  const novels = job._novels || [];
  const [mode, setMode] = useState("new");
  const [novelId, setNovelId] = useState("");
  const [offset, setOffset] = useState("0");
  const [sourceId, setSourceId] = useState("");
  const [sources, setSources] = useState([]);
  const [sourcesError, setSourcesError] = useState(null);
  const [flash, setFlash] = useState(null);
  const [barOpen, setBarOpen] = useState(false);
  const flashTimer = useRef(null);
  const listRef = useRef(null);
  const uid = useId();
  const editableMeta = metadata || {};
  const detectedSeries = editableMeta.series || "";
  const detectedVolume = editableMeta.volume_label
    || (editableMeta.series_index !== "" && editableMeta.series_index != null
      ? `Volume ${editableMeta.series_index}`
      : "");
  const [asVolume, setAsVolume] = useState(
    !!(detectedSeries || editableMeta.series_index !== "" && editableMeta.series_index != null),
  );
  const detectedLang = editableMeta.language || "";
  const [isRaw, setIsRaw] = useState(!!(job.options && job.options.is_raw));

  useEffect(() => {
    if (!asVolume || !detectedSeries || novelId) return;
    const normalize = value => String(value || "").trim().toLocaleLowerCase();
    const match = novels.find(
      novel => novel.can_edit && normalize(novel.title) === normalize(detectedSeries),
    );
    if (match) {
      setMode("append");
      setNovelId(String(match.id));
    }
  }, [asVolume, detectedSeries, novelId, novels]);

  useEffect(() => {
    if (mode !== "replace" || !novelId) { setSources([]); return; }
    let cancel = false;
    setSources([]); setSourcesError(null);
    catalogApi.novel(parseInt(novelId)).then(n => { if (!cancel) setSources(n.sources || []); })
      .catch(error => { if (!cancel) setSourcesError(error.message || "Could not load sources. Choose the novel again to retry."); });
    return () => { cancel = true; };
  }, [mode, novelId]);

  useEffect(() => () => clearTimeout(flashTimer.current), []);

  const buildBody = () => {
    if (mode === "append") return {
      mode: "append", novel_id: parseInt(novelId), offset: parseFloat(offset) || 0,
      is_raw: isRaw, as_volume: asVolume,
    };
    if (mode === "replace") return {
      mode: "replace", source_id: parseInt(sourceId), offset: parseFloat(offset) || 0,
      is_raw: isRaw, as_volume: false,
    };
    return { mode: "new", is_raw: isRaw, as_volume: asVolume };
  };
  const includedCount = segs.filter(s => s.include).length;
  const words = segs.reduce((total, s) => total + (s.include && s.word_count ? s.word_count : 0), 0);
  const warnings = segs.filter(s => s.include && s.kind === "chapter" && s.number == null).length;
  const commitDisabled = busy || includedCount === 0
    || (mode === "append" && !novelId)
    || (mode === "replace" && (!sourceId || !sources.some(source => source.id === Number(sourceId))))
    || (((mode === "append" && !asVolume) || mode === "replace") && !Number.isFinite(Number(offset)));
  const keys = rowKeys(segs);
  const destNovel = novels.find(n => String(n.id) === String(novelId));
  const destSource = sources.find(source => String(source.id) === String(sourceId));
  const destination = mode === "new" ? "New novel"
    : mode === "append" ? (destNovel ? `Append to ${destNovel.title}` : "Append to… choose a novel")
    : destSource ? `Replace ${destSource.label || destSource.adapter} (#${destSource.id})` : "Replace… choose a source";

  const pulse = key => {
    setFlash(key);
    clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 900);
  };
  const patchSeg = (i, body) => setPlan(p => ({ ...p, segments: p.segments.map((s, j) => j === i ? { ...s, ...body } : s) }));
  const patchMeta = body => setMetadata(p => ({ ...p, ...body }));
  const mergePrev = (i) => setPlan(p => {
    if (i <= 0) return p;
    const segments = p.segments.slice();
    const prev = segments[i - 1], cur = segments[i];
    segments[i - 1] = { ...prev, block_range: [prev.block_range[0], cur.block_range[1]],
      word_count: (prev.word_count || 0) + (cur.word_count || 0) };
    segments.splice(i, 1);
    return { ...p, segments };
  });
  const splitHalf = (i) => setPlan(p => {
    const segments = p.segments.slice();
    const s = segments[i];
    const [a, b] = s.block_range;
    if (b <= a) return p;
    const mid = Math.floor((a + b) / 2);
    segments.splice(i, 1,
      { ...s, block_range: [a, mid] },
      { ...s, id: s.id + "b", title: s.title + " (cont.)", block_range: [mid + 1, b], number: null });
    return { ...p, segments };
  });
  const onMerge = (i, event) => {
    mergePrev(i);
    pulse(keys[i - 1]);
    // Keyboard merges keep focus on the row that absorbed this one.
    if (event && event.detail === 0) {
      requestAnimationFrame(() => {
        const row = listRef.current && listRef.current.querySelector(`[data-seg-index="${i - 1}"]`);
        const target = row && (row.querySelector(".imp-seg-merge:not(:disabled)") || row.querySelector(".imp-seg-split"));
        if (target) target.focus();
      });
    }
  };
  const onSplit = (i) => { splitHalf(i); pulse(keys[i]); };

  return (
    <div className="imp-review">
      <section className="imp-card card imp-details" aria-labelledby={`${uid}-details`}>
        <div className="imp-card-head">
          <div>
            <p className="imp-eyebrow">Review</p>
            <h2 id={`${uid}-details`} className="imp-card-title">Book details</h2>
          </div>
          <p className="imp-card-note">These saved values override PDF/EPUB metadata and filename guesses.</p>
        </div>
        <div className="imp-fields">
          <label className="field f-title">
            <span>Book title</span>
            <input className="input" aria-label="Book title" value={editableMeta.title || ""}
                   onChange={e => patchMeta({ title: e.target.value })} placeholder="Enter the exact title" />
          </label>
          <label className="field f-author">
            <span>Author</span>
            <input className="input" aria-label="Author" value={editableMeta.author || ""}
                   onChange={e => patchMeta({ author: e.target.value })} placeholder="Optional" />
          </label>
          <label className="field f-series">
            <span>Series / novel name</span>
            <input className="input" aria-label="Series / novel name" value={editableMeta.series || ""}
                   onChange={e => patchMeta({ series: e.target.value })}
                   placeholder="e.g. Mushoku Tensei" />
          </label>
          <label className="field f-index">
            <span>Volume number</span>
            <input className="input" aria-label="Volume number" type="number" step="any"
                   value={editableMeta.series_index ?? ""}
                   onChange={e => patchMeta({ series_index: e.target.value })}
                   placeholder="e.g. 2" inputMode="decimal" />
          </label>
          <label className="field f-label">
            <span>Volume/group label</span>
            <input className="input" aria-label="Volume/group label" value={editableMeta.volume_label || ""}
                   onChange={e => patchMeta({ volume_label: e.target.value })}
                   placeholder="e.g. Volume 2" />
          </label>
          <label className="field f-lang">
            <span>Language code</span>
            <input className="input" aria-label="Language code" value={editableMeta.language || ""}
                   onChange={e => patchMeta({ language: e.target.value })}
                   placeholder="e.g. en, ja" />
          </label>
          <label className="field f-desc">
            <span>Description</span>
            <textarea className="input" aria-label="Description" value={editableMeta.description || ""}
                      onChange={e => patchMeta({ description: e.target.value })}
                      placeholder="Optional book description" rows={3} />
          </label>
        </div>
        <div className="imp-card-foot">
          <Button variant="ghost" size="sm" icon="check" loading={busy} onClick={onSave}>
            Save review
          </Button>
        </div>
      </section>

      <section className="imp-segs" aria-labelledby={`${uid}-segs`}>
        <div className="imp-segs-head">
          <div className="imp-segs-count">
            <h2 id={`${uid}-segs`} className="imp-card-title">{segs.length} segments</h2>
            <span className="imp-segs-sub">
              {includedCount} will be imported{words > 0 ? ` · ${words.toLocaleString()} words` : ""}
            </span>
          </div>
          {warnings > 0 && <Chip tone="warn" icon="alert">{warnings} unnumbered chapter{warnings === 1 ? "" : "s"}</Chip>}
        </div>
        <div className="imp-seg-list" ref={listRef}>
          {segs.map((s, i) => (
            <SegmentRow key={keys[i]} seg={s} index={i} canMerge={i > 0} flash={flash === keys[i]}
                        onPatch={body => patchSeg(i, body)}
                        onMerge={event => onMerge(i, event)} onSplit={() => onSplit(i)} />
          ))}
        </div>
        <div className="imp-options">
          <label className="check imp-toggle">
            <input type="checkbox" checked={isRaw} onChange={e => setIsRaw(e.target.checked)} />
            <span>These are raws — translate on read
              {detectedLang && <span className="imp-toggle-note">(detected: {detectedLang})</span>}
            </span>
          </label>
          <label className="check imp-toggle">
            <input type="checkbox" checked={asVolume} onChange={e => setAsVolume(e.target.checked)} />
            <span>Group this book as {detectedVolume || "a volume"}
              {detectedSeries && <span className="imp-toggle-note">in {detectedSeries}; append numbering is automatic</span>}
            </span>
          </label>
        </div>
      </section>

      <div className={"imp-commit" + (mode === "replace" ? " is-replace" : "") + (barOpen ? " is-open" : "")}>
        <button type="button" className="imp-commit-dest" aria-expanded={barOpen} onClick={() => setBarOpen(open => !open)}>
          <span className="imp-commit-dest-label">Destination · {includedCount} of {segs.length}</span>
          <span className="imp-commit-dest-name">{destination}</span>
          <Icon name="chevronUp" size={16} className="imp-commit-dest-chev" />
        </button>
        <div className="imp-commit-sum" aria-hidden="true">
          <b>{includedCount}</b><span>of {segs.length} segments</span>
        </div>
        <div className="seg fit imp-commit-mode" role="group" aria-label="Commit target">
          {MODES.map(m => (
            <button key={m.id} type="button" aria-pressed={mode === m.id} className={mode === m.id ? "active" : ""}
                    title={m.title}
                    onClick={() => { setMode(m.id); if (m.id === "replace") setSourceId(""); }}>
              {mode === m.id && <motion.span layoutId={`${uid}-mode`} className="seg-thumb" transition={springs.layout} aria-hidden="true" />}
              {m.label}
            </button>
          ))}
        </div>
        {(mode === "append" || mode === "replace") && (
          <select className="input imp-commit-select" value={novelId}
                  aria-label="Destination novel"
                  onChange={e => { setNovelId(e.target.value); setSourceId(""); }}>
            <option value="">Choose a novel…</option>
            {novels.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
        )}
        {mode === "replace" && novelId && (
          <select className="input imp-commit-select" aria-label="Source to replace" value={sourceId} onChange={e => setSourceId(e.target.value)}>
            <option value="">Choose a source…</option>
            {sources.map(s => <option key={s.id} value={s.id}>{(s.label || s.adapter) + ` (#${s.id})`}</option>)}
          </select>
        )}
        {((mode === "append" && !asVolume) || mode === "replace") && (
          <label className="imp-commit-offset" title="Chapter offset">
            <span aria-hidden="true">Offset</span>
            <input className="input" value={offset} onChange={e => setOffset(e.target.value)}
                   placeholder="offset" inputMode="decimal" aria-label="Chapter offset" />
          </label>
        )}
        <Button variant="primary" icon="check" className="imp-commit-go" disabled={commitDisabled} loading={busy}
                onClick={() => onCommit(buildBody())}>
          {mode === "replace" ? "Replace chapters" : "Commit"}
        </Button>
        {mode === "replace" && (
          <p className="imp-commit-note">
            <Icon name="alert" size={13} sw={2} />
            Replacing deletes that source's current chapters and rebuilds its part of the codex.
          </p>
        )}
        {mode === "replace" && sourcesError && <p role="alert" className="acct-err imp-commit-note">{sourcesError}</p>}
      </div>
    </div>
  );
}
