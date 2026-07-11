/* ============================================================
   Import (§6.9) — upload an EPUB/PDF, review the segmentation plan, commit.
   The multi-step nature is now a visible stepper: Upload → Parse → [OCR] →
   Review → Commit. Heavy work runs in the server-side import worker.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { API } from "../lib/api.js";
import { useAuth } from "../App.jsx";
import { Icon } from "../components/Icon.jsx";
import { Button, Chip, Cover, EmptyState, Loading, PageHeader, ProgressBar } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";
import { useTitle } from "../lib/hooks.js";

const IMPORT_KINDS = ["chapter", "frontmatter", "interlude", "backmatter"];
const IMPORT_BUSY = ["receiving", "uploaded", "parsing", "segmenting", "committing", "commit_running",
  "ocr_pending", "ocr_running", "ocr_paused"];
const IMPORT_STATUS_LABEL = {
  receiving: "Receiving…", uploaded: "Queued…", parsing: "Parsing…", segmenting: "Segmenting…",
  awaiting_ocr_confirm: "Scanned — needs OCR", ocr_pending: "OCR queued…", ocr_running: "Reading pages…",
  ocr_paused: "OCR paused (budget)", awaiting_review: "Ready to review",
  committing: "Committing…", commit_running: "Committing…",
  committed: "Committed", failed: "Failed", canceled: "Canceled",
};

/* Where a job sits in the wizard: 0 upload, 1 parse, 2 ocr, 3 review, 4 commit(ted). */
function stepOf(job) {
  if (!job) return 0;
  const s = job.status;
  if (["receiving", "uploaded", "parsing", "segmenting"].includes(s)) return 1;
  if (["awaiting_ocr_confirm", "ocr_pending", "ocr_running", "ocr_paused"].includes(s)) return 2;
  if (s === "awaiting_review") return 3;
  if (["committing", "commit_running", "committed"].includes(s)) return 4;
  return 1;
}

function Stepper({ job }) {
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

function UploadDrop({ onUploaded }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);
  const { toast } = useToast();

  async function send(file) {
    if (!file || busy) return;
    if (!/\.(epub|pdf)$/i.test(file.name)) { toast("Only .epub and .pdf files are supported.", { tone: "danger" }); return; }
    setBusy(true); setProgress(0);
    try {
      const r = await API.importFile(file, setProgress);
      onUploaded(r.id, r.duplicate_of);
    }
    catch (e) { toast(e.message || "Upload failed.", { tone: "danger" }); }
    finally { setBusy(false); setProgress(0); }
  }

  return (
    <div>
      <div className={"import-drop" + (drag ? " drag" : "")}
           onClick={() => !busy && inputRef.current && inputRef.current.click()}
           onDragOver={e => { e.preventDefault(); setDrag(true); }}
           onDragLeave={() => setDrag(false)}
           onDrop={e => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files[0]); }}>
        <Icon name="upload" size={28} className="muted" />
        <div className="import-drop-text">
          <b>{busy
            ? (progress > 0 && progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Uploading…")
            : "Drop an EPUB or PDF here, or click to choose"}</b>
          <span className="muted" style={{ fontSize: "var(--text-sm)" }}>
            We parse it (scanned PDFs are OCR'd), you review the chapters, then commit.
          </span>
        </div>
        <div className="row" style={{ marginLeft: "auto", gap: 6 }}>
          <Chip>.epub</Chip><Chip>.pdf</Chip>
        </div>
        <input ref={inputRef} type="file" accept=".epub,.pdf" style={{ display: "none" }}
               onChange={e => send(e.target.files[0])} />
      </div>
      {busy && progress > 0 && <ProgressBar size="sm" value={progress * 100} style={{ marginTop: 8 }} />}
    </div>
  );
}

/* Bulk import a server-side folder (admin; behind an Advanced disclosure). */
function FolderImport({ onQueued }) {
  const [open, setOpen] = useState(false);
  const [path, setPath] = useState("");
  const [autoCommit, setAutoCommit] = useState(true);
  const [groupSeries, setGroupSeries] = useState(true);
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  async function run() {
    setBusy(true);
    try {
      const r = await API.batchImport({
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
        Group EPUB volumes of one series into a single novel
      </label>
      <div className="row" style={{ gap: 10, marginTop: 12 }}>
        <Button variant="primary" icon="play" loading={busy} onClick={run}>Scan & import</Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>Close</Button>
      </div>
    </div>
  );
}

function DuplicateWarning({ dups, onOpenNovel }) {
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

function QualityBadge({ quality }) {
  if (!quality || quality.score == null) return null;
  const s = quality.score;
  const tone = s >= 85 ? "good" : s >= 60 ? "warn" : "bad";
  const tip = (quality.factors || []).map(f => `${f.ok ? "✓" : "✕"} ${f.label}: ${f.detail}`).join("\n");
  return <span className={"quality-badge q-" + tone} title={tip}>Quality {s}</span>;
}

function SegmentRow({ seg, onPatch, onMerge, onSplit, canMerge }) {
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
          {seg.part_label && <Chip style={{ marginRight: 6 }}>{seg.part_label}</Chip>}
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

function PlanEditor({ job, plan, setPlan, onCommit, busy }) {
  const segs = plan.segments || [];
  const novels = job._novels || [];
  const [mode, setMode] = useState("new");
  const [novelId, setNovelId] = useState("");
  const [offset, setOffset] = useState("0");
  const [sourceId, setSourceId] = useState("");
  const [sources, setSources] = useState([]);
  const detectedLang = (job.detected_meta && job.detected_meta.language) || "";
  const [isRaw, setIsRaw] = useState(!!(job.options && job.options.is_raw));

  useEffect(() => {
    if (mode !== "replace" || !novelId) { setSources([]); return; }
    let cancel = false;
    API.novel(parseInt(novelId)).then(n => { if (!cancel) setSources(n.sources || []); }).catch(() => {});
    return () => { cancel = true; };
  }, [mode, novelId]);

  const buildBody = () => {
    if (mode === "append") return { mode: "append", novel_id: parseInt(novelId), offset: parseFloat(offset) || 0, is_raw: isRaw };
    if (mode === "replace") return { mode: "replace", source_id: parseInt(sourceId), offset: parseFloat(offset) || 0, is_raw: isRaw };
    return { mode: "new", is_raw: isRaw };
  };
  const includedCount = segs.filter(s => s.include).length;
  const warnings = segs.filter(s => s.include && s.kind === "chapter" && s.number == null).length;
  const commitDisabled = busy || includedCount === 0
    || (mode === "append" && !novelId)
    || (mode === "replace" && !sourceId);

  const patchSeg = (i, body) => setPlan(p => ({ ...p, segments: p.segments.map((s, j) => j === i ? { ...s, ...body } : s) }));
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
        {(mode === "append" || mode === "replace") && (
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

function OcrConfirm({ job, onConfirm, busy }) {
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

function OcrProgress({ job }) {
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

export function ImportView() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [jobs, setJobs] = useState(null);
  const [sel, setSel] = useState(null);
  const [job, setJob] = useState(null);
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dupWarn, setDupWarn] = useState(null);
  const [seriesSel, setSeriesSel] = useState({});
  const novelsRef = useRef([]);
  useTitle("Import");

  const openNovel = (id) => navigate(`/n/${id}`);

  const loadJobs = useCallback(() => {
    API.importJobs().then(setJobs).catch(() => setJobs([]));
  }, []);
  useEffect(() => {
    loadJobs();
    API.novels().then(n => { novelsRef.current = n; }).catch(() => {});
  }, [loadJobs]);

  // Load + poll the selected job while it's being worked on server-side.
  useEffect(() => {
    if (sel == null) { setJob(null); setPlan(null); return; }
    let cancel = false, timer = null;
    const tick = () => {
      API.importJob(sel).then(j => {
        if (cancel) return;
        j._novels = novelsRef.current;
        setJob(j);
        setPlan(prev => {
          if (j.plan && (!prev || prev._forJob !== j.id || j.status === "committed")) {
            return { ...j.plan, _forJob: j.id };
          }
          return prev;
        });
        if (IMPORT_BUSY.includes(j.status)) timer = setTimeout(tick, 1500);
        else loadJobs();
      }).catch(() => {});
    };
    tick();
    return () => { cancel = true; if (timer) clearTimeout(timer); };
  }, [sel, loadJobs]);

  async function onUploaded(jobId, duplicateOf) {
    setDupWarn(duplicateOf && duplicateOf.length ? duplicateOf : null);
    loadJobs(); setSel(jobId);
  }

  async function commitSeriesNow() {
    const ids = Object.keys(seriesSel).filter(k => seriesSel[k]).map(Number);
    if (ids.length < 2) return;
    setBusy(true);
    try {
      const r = await API.commitSeries(ids);
      toast(`Committed ${ids.length} volumes into one novel.`, { tone: "ok" });
      setSeriesSel({}); loadJobs();
      if (r.novel_id) openNovel(r.novel_id);
    } catch (e) { toast(e.message || "Series commit failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  }
  const seriesCount = Object.values(seriesSel).filter(Boolean).length;

  async function commit(body) {
    setBusy(true);
    try {
      if (plan) await API.updateImportPlan(sel, { version: plan.version || 1, segments: plan.segments });
      await API.commitImport(sel, body);
      toast("Commit started…", { tone: "ok" });
    } catch (e) { toast(e.message || "Commit failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  async function confirmOcr(body) {
    setBusy(true);
    try { await API.confirmOcr(sel, body); toast("OCR started…", { tone: "ok" }); }
    catch (e) { toast(e.message || "Could not start OCR.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  async function removeJob(jid) {
    await API.deleteImport(jid).catch(() => {});
    if (sel === jid) { setSel(null); }
    loadJobs();
  }

  const meta = (job && job.detected_meta) || {};
  const committedNovel = job && job.status === "committed" && job.novel_id;

  return (
    <div className="page page-enter">
      <PageHeader title="Import a book"
        subtitle="Bring an EPUB or PDF into your library — chapters, cover and illustrations. Scanned PDFs are OCR'd." />

      <UploadDrop onUploaded={onUploaded} />
      {user && user.role === "admin" && <FolderImport onQueued={loadJobs} />}
      {dupWarn && <DuplicateWarning dups={dupWarn} onOpenNovel={openNovel} />}

      <div className="import-cols">
        {/* Jobs list */}
        <div>
          <p className="section-eyebrow">Recent imports</p>
          {seriesCount >= 2 && (
            <div className="card" style={{ padding: "8px 10px", marginBottom: 8, display: "flex", gap: 8, alignItems: "center" }}>
              <span className="grow" style={{ fontSize: "var(--text-sm)" }}>{seriesCount} selected</span>
              <Button variant="primary" size="sm" icon="layers" loading={busy} onClick={commitSeriesNow}>Commit as series</Button>
            </div>
          )}
          {jobs == null ? (
            <Loading label="Loading…" />
          ) : jobs.length === 0 ? (
            <div className="muted" style={{ fontSize: "var(--text-sm)", padding: 8 }}>No imports yet.</div>
          ) : (
            <div className="card" style={{ padding: 6 }}>
              {jobs.map(j => (
                <div key={j.id} className={"import-job-row" + (sel === j.id ? " active" : "")} onClick={() => setSel(j.id)}>
                  {j.status === "awaiting_review" && (
                    <input type="checkbox" title="Select for a series commit"
                           checked={!!seriesSel[j.id]}
                           onClick={e => e.stopPropagation()}
                           onChange={e => setSeriesSel(prev => ({ ...prev, [j.id]: e.target.checked }))} />
                  )}
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }} className="truncate">
                      {(j.detected_meta && j.detected_meta.title) || j.filename || `Job ${j.id}`}
                    </div>
                    <div className="muted" style={{ fontSize: "var(--text-xs)" }}>
                      {(IMPORT_STATUS_LABEL[j.status] || j.status)
                        + ((j.detected_meta && j.detected_meta.series) ? " · " + j.detected_meta.series : "")}
                    </div>
                  </div>
                  <button className="icon-btn plain" title="Delete" aria-label="Delete import"
                          onClick={e => { e.stopPropagation(); removeJob(j.id); }}>
                    <Icon name="x" size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Selected job detail */}
        <div>
          {job == null ? (
            <EmptyState icon="book" title="Select an import" body="Upload an EPUB or pick a recent import to review it." />
          ) : (
            <>
              <Stepper job={job} />
              <div className="import-meta card">
                {meta.cover_url && <Cover src={meta.cover_url} title={meta.title || ""} />}
                <div className="grow" style={{ minWidth: 0 }}>
                  <b>{meta.title || job.filename || "Untitled"}</b>
                  {meta.author && <div className="muted" style={{ fontSize: "var(--text-sm)" }}>{meta.author}</div>}
                  <div className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 4 }}>
                    {IMPORT_STATUS_LABEL[job.status] || job.status}{job.stage ? " · " + job.stage : ""}
                  </div>
                  <div className="row wrap" style={{ gap: 8, marginTop: 6 }}>
                    {job.stats && job.stats.images != null && (
                      <span className="muted" style={{ fontSize: "var(--text-xs)" }}>
                        {job.stats.segments || 0} segments · {job.stats.images || 0} images
                      </span>
                    )}
                    {job.stats && <QualityBadge quality={job.stats.quality} />}
                  </div>
                </div>
              </div>
              {job.error && (
                <div className="card" style={{ padding: "10px 14px", color: "var(--danger)", fontSize: "var(--text-sm)", marginBottom: 12 }}>
                  {job.error}
                </div>
              )}

              {committedNovel && (
                <div className="card pad" style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
                  <Icon name="check" size={18} style={{ color: "var(--ok)" }} />
                  <b className="grow">Imported into your library.</b>
                  <Button variant="primary" onClick={() => openNovel(job.novel_id)}>Open novel</Button>
                </div>
              )}

              {job.status === "awaiting_ocr_confirm"
                ? <OcrConfirm job={job} onConfirm={confirmOcr} busy={busy} />
                : ["ocr_pending", "ocr_running", "ocr_paused"].includes(job.status)
                  ? <OcrProgress job={job} />
                  : job.status === "awaiting_review" && plan
                    ? <PlanEditor job={job} plan={plan} setPlan={setPlan} onCommit={commit} busy={busy} />
                    : IMPORT_BUSY.includes(job.status)
                      ? <Loading label={IMPORT_STATUS_LABEL[job.status] || "Working…"} />
                      : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
