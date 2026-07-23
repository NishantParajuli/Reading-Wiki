import React, { useEffect, useRef, useState } from "react";

import { acquisitionApi } from "./api.js";
import { catalogApi } from "../catalog/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, ProgressBar } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";

export const IMPORT_KINDS = ["chapter", "frontmatter", "interlude", "backmatter"];
export const IMPORT_BUSY = ["receiving", "uploaded", "parsing", "segmenting", "committing", "commit_running",
  "ocr_pending", "ocr_running", "ocr_paused"];
export const IMPORT_STATUS_LABEL = {
  receiving: "Receiving…", uploaded: "Queued…", parsing: "Parsing…", segmenting: "Segmenting…",
  awaiting_ocr_confirm: "Scanned — needs OCR", ocr_pending: "OCR queued…", ocr_running: "Reading pages…",
  ocr_paused: "OCR paused (budget)", awaiting_review: "Ready to review",
  committing: "Committing…", commit_running: "Committing…",
  committed: "Committed", failed: "Failed", canceled: "Canceled",
};

/* Where a job sits in the wizard: 0 upload, 1 parse, 2 ocr, 3 review, 4 commit(ted). */
export function stepOf(job) {
  if (!job) return 0;
  const s = job.status;
  if (["receiving", "uploaded", "parsing", "segmenting"].includes(s)) return 1;
  if (["awaiting_ocr_confirm", "ocr_pending", "ocr_running", "ocr_paused"].includes(s)) return 2;
  if (s === "awaiting_review") return 3;
  if (["committing", "commit_running", "committed"].includes(s)) return 4;
  return 1;
}

export function Stepper({ job }) {
  const hasOcr = job && ["awaiting_ocr_confirm", "ocr_pending", "ocr_running", "ocr_paused"].includes(job.status)
    || (job && job.cost_estimate && job.cost_estimate.scanned_pages != null);
  const steps = ["Upload", "Parse", ...(hasOcr ? ["OCR"] : []), "Review", "Commit"];
  const rawIdx = stepOf(job);
  const idx = hasOcr ? rawIdx : (rawIdx >= 3 ? rawIdx - 1 : rawIdx);
  const committed = job && job.status === "committed";
  return (
    <div className="stepper" aria-label="Import progress">
      {steps.map((label, i) => (
        <React.Fragment key={label}>
          {i > 0 && <span className="stepper-line" aria-hidden />}
          <span className={"stepper-step" + (i < idx || committed ? " done" : i === idx ? " active" : "")}>
            <span className="ss-dot">{i < idx || committed ? <Icon name="check" size={13} sw={2.6} /> : i + 1}</span>
            {label}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
}

export function UploadDrop({ onUploaded }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);
  const { toast } = useToast();

  async function send(input) {
    if (!input || busy) return;
    const files = Array.from(input instanceof File ? [input] : input);
    if (!files.length) return;
    const unsupported = files.filter(file => !/\.(epub|pdf)$/i.test(file.name));
    if (unsupported.length) {
      toast("Only .epub and .pdf files are supported.", { tone: "danger" });
      return;
    }
    setBusy(true); setProgress(0);
    let queued = 0;
    const failures = [];
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      try {
        const r = await acquisitionApi.importFile(
          file,
          value => setProgress((index + value) / files.length),
        );
        queued += 1;
        onUploaded(r.id, r.duplicate_of);
      } catch (error) {
        failures.push({ file, error });
      }
    }
    if (files.length > 1 && queued) {
      toast(
        failures.length
          ? `Queued ${queued} of ${files.length} books; ${failures.length} failed.`
          : `Queued ${queued} books for import.`,
        { tone: failures.length ? "warn" : "ok" },
      );
    } else if (failures.length) {
      toast(failures[0].error.message || "Upload failed.", { tone: "danger" });
    }
    setBusy(false); setProgress(0);
  }

  return (
    <div>
      <div className={"import-drop" + (drag ? " drag" : "")}
           onClick={() => !busy && inputRef.current && inputRef.current.click()}
           onDragOver={e => { e.preventDefault(); setDrag(true); }}
           onDragLeave={() => setDrag(false)}
           onDrop={e => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}>
        <Icon name="upload" size={28} className="muted" />
        <div className="import-drop-text">
          <b>{busy
            ? (progress > 0 && progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Uploading…")
            : "Drop one or more EPUB/PDF books here, or click to choose"}</b>
          <span className="muted" style={{ fontSize: "var(--text-sm)" }}>
            Upload several volumes together, review them, then commit or append them as one series.
          </span>
        </div>
        <div className="row" style={{ marginLeft: "auto", gap: 6 }}>
          <Chip>.epub</Chip><Chip>.pdf</Chip>
        </div>
        <input ref={inputRef} type="file" accept=".epub,.pdf" multiple style={{ display: "none" }}
               onChange={e => { send(e.target.files); e.target.value = ""; }} />
      </div>
      {busy && progress > 0 && <ProgressBar size="sm" value={progress * 100} style={{ marginTop: 8 }} />}
    </div>
  );
}

/* Bulk import a server-side folder (admin; behind an Advanced disclosure). */
export function FolderImport({ onQueued }) {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [autoCommit, setAutoCommit] = useState(true);
  const [groupSeries, setGroupSeries] = useState(true);
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  async function run() {
    setBusy(true);
    try {
      const r = await acquisitionApi.batchImport({
        path: path.trim() || null, recursive: true, auto_commit: autoCommit, group_series: groupSeries,
      });
      toast(`Queued ${r.count} file(s).`, { tone: "ok" });
      onQueued && onQueued();
    } catch (e) { toast(e.message || "Batch import failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  if (!open) {
    return (
      <Button variant="ghost" size="sm" icon="layers" style={{ marginTop: 10 }} onClick={() => setOpen(true)}>
        Advanced: import a folder / Calibre library
      </Button>
    );
  }
  return (
    <div className="card pad" style={{ marginTop: 10 }}>
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Folder / batch import</p>
      <input className="input" value={path} onChange={e => setPath(e.target.value)}
             placeholder="Server path to a folder (blank = watched incoming dir)" style={{ marginBottom: 10 }} />
      <label className="check">
        <input type="checkbox" checked={autoCommit} onChange={e => setAutoCommit(e.target.checked)} />
        Auto-commit each book (skip manual review)
      </label>
      <label className="check" style={{ marginTop: 6 }}>
        <input type="checkbox" checked={groupSeries} onChange={e => setGroupSeries(e.target.checked)} />
        Group detected EPUB/PDF volumes of one series into a single novel
      </label>
      <div className="row" style={{ gap: 10, marginTop: 12 }}>
        <Button variant="primary" icon="play" loading={busy} onClick={run}>Scan & import</Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>Close</Button>
      </div>
    </div>
  );
}

export function DuplicateWarning({ dups, onOpenNovel }) {
  const committed = (dups || []).filter(d => d.novel_id);
  if (!committed.length) return null;
  const d = committed[0];
  return (
    <div className="card" style={{ padding: "10px 14px", margin: "12px 0", display: "flex", gap: 10, alignItems: "center", borderLeft: "3px solid var(--warn)" }}>
      <Icon name="alert" size={16} className="muted" />
      <div className="grow" style={{ fontSize: "var(--text-sm)" }}>
        You already imported this file{d.novel_title ? <> into <b>{d.novel_title}</b></> : null}. Committing again makes a separate copy.
      </div>
      {d.novel_id && <Button variant="ghost" size="sm" onClick={() => onOpenNovel(d.novel_id)}>Open</Button>}
    </div>
  );
}

export function QualityBadge({ quality }) {
  if (!quality || quality.score == null) return null;
  const s = quality.score;
  const tone = s >= 85 ? "good" : s >= 60 ? "warn" : "bad";
  const tip = (quality.factors || []).map(f => `${f.ok ? "✓" : "✕"} ${f.label}: ${f.detail}`).join("\n");
  return <span className={"quality-badge q-" + tone} title={tip}>Quality {s}</span>;
}

export function SegmentRow({ seg, onPatch, onMerge, onSplit, canMerge }) {
  const wc = seg.word_count != null ? `${seg.word_count.toLocaleString()} words` : "";
  return (
    <div className={"seg-row" + (seg.include ? "" : " excluded")}>
      <label className="seg-include" title={seg.include ? "Included" : "Excluded"}>
        <input type="checkbox" checked={!!seg.include} onChange={e => onPatch({ include: e.target.checked })} />
      </label>
      <div className="seg-main">
        <div className="seg-line1">
          <input className="seg-title" value={seg.title || ""}
                 onChange={e => onPatch({ title: e.target.value })} placeholder="Untitled" />
          <select className="seg-kind" value={seg.kind} onChange={e => onPatch({ kind: e.target.value })}>
            {IMPORT_KINDS.map(k => <option key={k} value={k}>{k}</option>)}
          </select>
          <input className="seg-num" value={seg.number == null ? "" : seg.number} placeholder="#"
                 title="Chapter number" inputMode="decimal"
                 onChange={e => { const v = e.target.value.trim(); onPatch({ number: v === "" ? null : parseFloat(v) }); }} />
        </div>
        <div className="seg-line2 muted">
          <input className="input" value={seg.part_label || ""}
                 aria-label={`Volume/group for ${seg.title || "untitled segment"}`}
                 onChange={e => onPatch({ part_label: e.target.value || null })}
                 placeholder="Volume/group"
                 style={{ width: 125, height: 25, marginRight: 8, padding: "2px 7px", fontSize: "var(--text-xs)" }} />
          <span className="mono" style={{ marginRight: 8 }}>[{seg.block_range[0]}–{seg.block_range[1]}]</span>
          {wc && <span style={{ marginRight: 8 }}>{wc}</span>}
          {seg.first_line && <span className="seg-first">{seg.first_line}</span>}
        </div>
      </div>
      <div className="seg-actions">
        <button className="icon-btn plain" title="Merge into previous" aria-label="Merge into previous" disabled={!canMerge} onClick={onMerge}>
          <Icon name="merge" size={15} />
        </button>
        <button className="icon-btn plain" title="Split in half" aria-label="Split in half" onClick={onSplit}>
          <Icon name="scissors" size={15} />
        </button>
      </div>
    </div>
  );
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
    catalogApi.novel(parseInt(novelId)).then(n => { if (!cancel) setSources(n.sources || []); }).catch(() => {});
    return () => { cancel = true; };
  }, [mode, novelId]);

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
  const warnings = segs.filter(s => s.include && s.kind === "chapter" && s.number == null).length;
  const commitDisabled = busy || includedCount === 0
    || (mode === "append" && !novelId)
    || (mode === "replace" && !sourceId);

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

  return (
    <div>
      <div className="card pad" style={{ marginBottom: 10 }}>
        <p className="section-eyebrow" style={{ marginTop: 0 }}>Book details</p>
        <p className="muted" style={{ margin: "0 0 10px", fontSize: "var(--text-xs)" }}>
          These saved values override PDF/EPUB metadata and filename guesses.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
          <label>
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>Book title</span>
            <input className="input" aria-label="Book title" value={editableMeta.title || ""}
                   onChange={e => patchMeta({ title: e.target.value })} placeholder="Enter the exact title" />
          </label>
          <label>
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>Author</span>
            <input className="input" aria-label="Author" value={editableMeta.author || ""}
                   onChange={e => patchMeta({ author: e.target.value })} placeholder="Optional" />
          </label>
          <label>
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>Series / novel name</span>
            <input className="input" aria-label="Series / novel name" value={editableMeta.series || ""}
                   onChange={e => patchMeta({ series: e.target.value })}
                   placeholder="e.g. Mushoku Tensei" />
          </label>
          <label>
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>Volume number</span>
            <input className="input" aria-label="Volume number" type="number" step="any"
                   value={editableMeta.series_index ?? ""}
                   onChange={e => patchMeta({ series_index: e.target.value })}
                   placeholder="e.g. 2" inputMode="decimal" />
          </label>
          <label>
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>Volume/group label</span>
            <input className="input" aria-label="Volume/group label" value={editableMeta.volume_label || ""}
                   onChange={e => patchMeta({ volume_label: e.target.value })}
                   placeholder="e.g. Volume 2" />
          </label>
          <label>
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>Language code</span>
            <input className="input" aria-label="Language code" value={editableMeta.language || ""}
                   onChange={e => patchMeta({ language: e.target.value })}
                   placeholder="e.g. en, ja" />
          </label>
        </div>
        <label style={{ display: "block", marginTop: 10 }}>
          <span className="muted" style={{ fontSize: "var(--text-xs)" }}>Description</span>
          <textarea className="input" aria-label="Description" value={editableMeta.description || ""}
                    onChange={e => patchMeta({ description: e.target.value })}
                    placeholder="Optional book description" rows={3}
                    style={{ resize: "vertical", minHeight: 70 }} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
          <Button variant="ghost" size="sm" icon="check" loading={busy} onClick={onSave}>
            Save review
          </Button>
        </div>
      </div>
      <div className="card plan-head">
        <div>
          <b>{segs.length} segments</b>
          <span className="muted" style={{ marginLeft: 8, fontSize: "var(--text-sm)" }}>{includedCount} will be imported</span>
        </div>
        {warnings > 0 && <Chip tone="warn" icon="alert">{warnings} unnumbered chapter{warnings === 1 ? "" : "s"}</Chip>}
      </div>
      <div className="seg-list">
        {segs.map((s, i) => (
          <SegmentRow key={s.id + ":" + i} seg={s} canMerge={i > 0}
                      onPatch={body => patchSeg(i, body)}
                      onMerge={() => mergePrev(i)} onSplit={() => splitHalf(i)} />
        ))}
      </div>
      <label className="check" style={{ margin: "10px 2px 0" }}>
        <input type="checkbox" checked={isRaw} onChange={e => setIsRaw(e.target.checked)} />
        These are raws — translate on read
        {detectedLang && <span className="muted" style={{ fontSize: "var(--text-xs)" }}>(detected: {detectedLang})</span>}
      </label>
      <label className="check" style={{ margin: "8px 2px 0" }}>
        <input type="checkbox" checked={asVolume} onChange={e => setAsVolume(e.target.checked)} />
        Group this book as {detectedVolume || "a volume"}
        {detectedSeries && (
          <span className="muted" style={{ fontSize: "var(--text-xs)" }}>
            in {detectedSeries}; append numbering is automatic
          </span>
        )}
      </label>
      <div className="card commit-bar">
        <div className="seg fit" role="group" aria-label="Commit target">
          <button className={mode === "new" ? "active" : ""} onClick={() => setMode("new")}>New novel</button>
          <button className={mode === "append" ? "active" : ""} onClick={() => setMode("append")}>Append to…</button>
          <button className={mode === "replace" ? "active" : ""} title="Overwrite an existing source's chapters" onClick={() => setMode("replace")}>Replace…</button>
        </div>
        {(mode === "append" || mode === "replace") && (
          <select className="input" style={{ flex: "1 1 160px", width: "auto" }} value={novelId}
                  onChange={e => { setNovelId(e.target.value); setSourceId(""); }}>
            <option value="">Choose a novel…</option>
            {novels.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
        )}
        {mode === "replace" && novelId && (
          <select className="input" style={{ flex: "1 1 160px", width: "auto" }} value={sourceId} onChange={e => setSourceId(e.target.value)}>
            <option value="">Choose a source…</option>
            {sources.map(s => <option key={s.id} value={s.id}>{(s.label || s.adapter) + ` (#${s.id})`}</option>)}
          </select>
        )}
        {((mode === "append" && !asVolume) || mode === "replace") && (
          <input className="input" style={{ flex: "0 0 110px", width: "auto" }} value={offset}
                 onChange={e => setOffset(e.target.value)} placeholder="offset" inputMode="decimal" title="Chapter offset" />
        )}
        <Button variant="primary" icon="check" disabled={commitDisabled} loading={busy}
                onClick={() => onCommit(buildBody())}>
          {mode === "replace" ? "Replace chapters" : "Commit"}
        </Button>
      </div>
      {mode === "replace" && (
        <p className="muted" style={{ fontSize: "var(--text-xs)", margin: "8px 2px 0" }}>
          Replacing deletes that source's current chapters and rebuilds its part of the codex.
        </p>
      )}
    </div>
  );
}

export function OcrConfirm({ job, onConfirm, busy }) {
  const [geminiFirst, setGeminiFirst] = useState(false);
  const est = job.cost_estimate || {};
  const pages = est.scanned_pages != null ? est.scanned_pages : (job.stats && job.stats.page_count) || 0;
  return (
    <div className="card pad-lg">
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Scanned PDF — needs OCR</p>
      <p style={{ margin: "0 0 8px", fontSize: "var(--text-md)" }}>
        {pages.toLocaleString()} pages look scanned. We'll read them with the local OCR engine and escalate hard pages to Gemini vision.
      </p>
      {est.est_gemini_requests != null && (
        <p className="muted" style={{ fontSize: "var(--text-sm)", margin: "0 0 10px" }}>
          ~{est.est_gemini_requests.toLocaleString()} Gemini requests (~{est.est_minutes} min)
          {est.budget_remaining != null ? ` · ${est.budget_remaining.toLocaleString()} of today's quota left` : ""}
        </p>
      )}
      <label className="check" style={{ marginBottom: 12 }}>
        <input type="checkbox" checked={geminiFirst} onChange={e => setGeminiFirst(e.target.checked)} />
        Use Gemini for every page (skip the local engine — higher quality, more quota)
      </label>
      <div className="row" style={{ gap: 10 }}>
        <Button variant="primary" icon="play" loading={busy} onClick={() => onConfirm({ gemini_first: geminiFirst })}>Run OCR</Button>
      </div>
    </div>
  );
}

export function OcrProgress({ job }) {
  const p = job.progress || {};
  const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
  const paused = job.status === "ocr_paused";
  return (
    <div className="card pad-lg">
      <div className="row" style={{ gap: 8, marginBottom: 10 }}>
        <Icon name={paused ? "pause" : "cpu"} size={16} className="muted" />
        <b className="grow">{IMPORT_STATUS_LABEL[job.status] || "Reading pages…"}</b>
        {p.total ? <span className="mono muted" style={{ fontSize: "var(--text-sm)" }}>{p.done}/{p.total}</span> : null}
      </div>
      <ProgressBar size="sm" value={pct} />
      {paused && (
        <p className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 8, marginBottom: 0 }}>
          Gemini's daily free quota is used up. This resumes automatically tomorrow — no pages are re-read.
        </p>
      )}
    </div>
  );
}
