/* ============================================================
   Import wizard parts: the tideline stepper, the book header card,
   the OCR / working / committed / error states, duplicate warning and the
   admin folder import. The basin lives in ImportBasin.jsx and the review
   editor in ImportReview.jsx; both are re-exported from here.
   ============================================================ */
import React, { useEffect, useState } from "react";

import { acquisitionApi } from "./api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Cover } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { AnimatePresence, motion, springs } from "../../motion/index.js";
import { IMPORT_STATUS_LABEL, OCR_STATUSES, importTone, stepOf } from "./importStatus.js";

export { IMPORT_BUSY, IMPORT_KINDS, IMPORT_STATUS_LABEL, stepOf } from "./importStatus.js";
export { UploadDrop } from "./ImportBasin.jsx";
export { PlanEditor, SegmentRow } from "./ImportReview.jsx";

const reveal = {
  initial: { height: 0, opacity: 0 },
  animate: { height: "auto", opacity: 1, transition: { height: springs.smooth, opacity: { duration: 0.3, delay: 0.06 } } },
  exit: { height: 0, opacity: 0, transition: { duration: 0.22, ease: [0.55, 0, 1, 0.45] } },
};

/* ---------- the tideline: Upload → Parse → [OCR] → Review → Commit ---------- */
export function Stepper({ job }) {
  const hasOcr = job && OCR_STATUSES.includes(job.status)
    || (job && job.cost_estimate && job.cost_estimate.scanned_pages != null);
  const steps = ["Upload", "Parse", ...(hasOcr ? ["OCR"] : []), "Review", "Commit"];
  const rawIdx = stepOf(job);
  const idx = hasOcr ? rawIdx : (rawIdx >= 3 ? rawIdx - 1 : rawIdx);
  const committed = !!job && job.status === "committed";
  const tone = importTone(job && job.status);
  const stopped = tone === "failed" || (job && job.status === "canceled");
  const fill = committed ? 1 : Math.min(1, idx / (steps.length - 1));
  const phase = stopped ? "stopped" : tone === "working" ? "working" : tone === "paused" ? "paused" : "waiting";
  const spoken = { stopped: "stopped", working: "in progress", paused: "paused", waiting: "waiting for you" };
  return (
    <div className={["imp-tide", committed ? "is-complete" : "", `is-${phase}`].filter(Boolean).join(" ")}
         style={{ "--steps": steps.length, "--fill": fill }}>
      <div className="imp-tide-rail" aria-hidden="true"><span className="imp-tide-flow" /></div>
      <ol className="imp-tide-steps" aria-label="Import progress">
        {steps.map((label, i) => {
          const done = i < idx || committed;
          const current = !committed && i === idx;
          const state = done ? "done" : current ? phase : "next";
          return (
            <li key={label} className={`imp-tide-step is-${state}`} style={{ "--i": i }}
                aria-current={current ? "step" : undefined}>
              <span className="imp-tide-node" aria-hidden="true">
                {done ? <Icon name="check" size={13} sw={2.6} />
                  : state === "stopped" ? <Icon name="x" size={12} sw={2.6} />
                  : state === "next" ? <span className="imp-tide-num">{i + 1}</span>
                  : <i className="imp-tide-core" />}
              </span>
              <span className="imp-tide-label">{label}</span>
              {(done || current) && <span className="sr-only">{done ? " (done)" : ` (${spoken[phase]})`}</span>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* Re-print the generated jacket only once typing settles. */
function useSettled(value, delay = 650) {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

export function QualityBadge({ quality }) {
  if (!quality || quality.score == null) return null;
  const s = quality.score;
  const tone = s >= 85 ? "good" : s >= 60 ? "warn" : "bad";
  const tip = (quality.factors || []).map(f => `${f.ok ? "✓" : "✕"} ${f.label}: ${f.detail}`).join("\n");
  const r = 17;
  const circumference = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, Number(s) || 0));
  return (
    <span className={"quality-badge q-" + tone} title={tip} role="img" aria-label={`Quality ${s} of 100`}>
      <svg viewBox="0 0 42 42" aria-hidden="true" focusable="false">
        <circle className="qb-track" cx="21" cy="21" r={r} />
        <circle className="qb-fill" cx="21" cy="21" r={r} strokeDasharray={circumference}
                strokeDashoffset={circumference * (1 - pct / 100)} transform="rotate(-90 21 21)" />
      </svg>
      <span className="qb-num">{s}</span>
      <span className="qb-label">Quality</span>
    </span>
  );
}

/* The book being imported: jacket, title, status, what was found. */
export function JobHeader({ job, meta }) {
  const detected = (job.detected_meta && job.detected_meta.title) || job.filename || "Untitled";
  const jacketTitle = useSettled(meta.title || detected);
  const title = meta.title || job.filename || "Untitled";
  const tone = importTone(job.status);
  const stats = job.stats;
  const misses = ((stats && stats.quality && stats.quality.factors) || []).filter(f => !f.ok).slice(0, 3);
  return (
    <header className="imp-job card" data-spotlight>
      <div className="imp-job-jacket" key={meta.cover_url || jacketTitle}>
        <Cover src={meta.cover_url} title={jacketTitle} author={meta.author} tilt={8} />
      </div>
      <div className="imp-job-body">
        {job.filename && <p className="imp-job-file" title={job.filename}>{job.filename}</p>}
        <h2 className="imp-job-title">{title}</h2>
        {meta.author && <p className="imp-job-author">{meta.author}</p>}
        <div className="imp-job-meta">
          <span className={`imp-status tone-${tone}`}>
            <i className="imp-dot" aria-hidden="true" />
            {IMPORT_STATUS_LABEL[job.status] || job.status}
            {job.stage ? <span className="imp-status-stage"> · {job.stage}</span> : null}
          </span>
          {stats && stats.images != null && (
            <span className="imp-job-stat">{stats.segments || 0} segments · {stats.images || 0} images</span>
          )}
        </div>
        {misses.length > 0 && (
          <ul className="imp-job-notes" aria-label="Quality notes">
            {misses.map(f => (
              <li key={f.label}><Icon name="alert" size={12} sw={2} /><span><b>{f.label}</b>{f.detail ? ` — ${f.detail}` : ""}</span></li>
            ))}
          </ul>
        )}
      </div>
      {stats && <QualityBadge quality={stats.quality} />}
    </header>
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

  return (
    <div className="imp-folder-wrap">
      {!open && (
        <Button variant="ghost" size="sm" icon="layers" className="imp-folder-toggle" onClick={() => setOpen(true)}>
          Advanced: import a folder / Calibre library
        </Button>
      )}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="folder" className="imp-folder-clip" {...reveal}>
            <div className="imp-folder card">
              <p className="section-eyebrow">Folder / batch import</p>
              <label className="field">
                <span>Server folder</span>
                <input className="input" value={path} onChange={e => setPath(e.target.value)} spellCheck={false}
                       placeholder="Blank = the watched incoming folder" />
              </label>
              <label className="check">
                <input type="checkbox" checked={autoCommit} onChange={e => setAutoCommit(e.target.checked)} />
                Auto-commit each book (skip manual review)
              </label>
              <label className="check">
                <input type="checkbox" checked={groupSeries} onChange={e => setGroupSeries(e.target.checked)} />
                Group detected EPUB/PDF volumes of one series into a single novel
              </label>
              <div className="imp-folder-actions">
                <Button variant="primary" size="sm" icon="play" loading={busy} onClick={run}>Scan & import</Button>
                <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Close</Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function DuplicateWarning({ dups, onOpenNovel }) {
  const committed = (dups || []).filter(d => d.novel_id);
  if (!committed.length) return null;
  const d = committed[0];
  return (
    <div className="imp-dup">
      <span className="imp-panel-icon is-warn" aria-hidden="true"><Icon name="alert" size={16} /></span>
      <p className="grow">
        You already imported this file{d.novel_title ? <> into <b>{d.novel_title}</b></> : null}. Committing again makes a separate copy.
      </p>
      {d.novel_id && <Button variant="ghost" size="sm" iconRight="arrowRight" onClick={() => onOpenNovel(d.novel_id)}>Open</Button>}
    </div>
  );
}

/* A scanned page under a reading beam. */
function ScanGlyph() {
  return (
    <svg className="imp-scan" viewBox="0 0 72 88" aria-hidden="true" focusable="false">
      <rect className="imp-scan-page" x="8" y="6" width="56" height="76" rx="6" />
      <path className="imp-scan-lines" d="M18 22h36M18 30h30M18 38h36M18 46h24M18 54h34M18 62h28M18 70h20" />
      <rect className="imp-scan-beam" x="4" y="0" width="64" height="10" rx="5" />
    </svg>
  );
}

export function OcrConfirm({ job, onConfirm, busy }) {
  const [geminiFirst, setGeminiFirst] = useState(false);
  const est = job.cost_estimate || {};
  const pages = est.scanned_pages != null ? est.scanned_pages : (job.stats && job.stats.page_count) || 0;
  return (
    <section className="imp-panel imp-ocr card">
      <ScanGlyph />
      <div className="imp-ocr-body">
        <p className="imp-eyebrow">Scanned pages found</p>
        <h2 className="imp-panel-title">Read the text in this scanned PDF</h2>
        <p className="imp-panel-lede">
          {pages.toLocaleString()} pages look scanned. We'll read them with the local OCR engine and escalate hard pages to Gemini vision.
        </p>
        {est.est_gemini_requests != null && (
          <dl className="imp-figures">
            <div><dt>Gemini requests</dt><dd>~{est.est_gemini_requests.toLocaleString()}</dd></div>
            {est.est_minutes != null && <div><dt>Estimated time</dt><dd>~{est.est_minutes} min</dd></div>}
            {est.budget_remaining != null && <div><dt>Today's quota left</dt><dd>{est.budget_remaining.toLocaleString()}</dd></div>}
          </dl>
        )}
        <label className="check imp-toggle">
          <input type="checkbox" checked={geminiFirst} onChange={e => setGeminiFirst(e.target.checked)} />
          <span>Use Gemini for every page <span className="imp-toggle-note">Skips the local engine — higher quality, more quota</span></span>
        </label>
        <div className="imp-panel-actions">
          <Button variant="primary" icon="play" loading={busy} onClick={() => onConfirm({ gemini_first: geminiFirst })}>Run OCR</Button>
        </div>
      </div>
    </section>
  );
}

const EDGE_PAGES = 48;

/* OCR progress as a book's fore-edge: one sliver lights per page range read. */
export function OcrProgress({ job }) {
  const p = job.progress || {};
  const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
  const paused = job.status === "ocr_paused";
  const lit = p.total ? Math.round((Math.min(p.done, p.total) / p.total) * EDGE_PAGES) : 0;
  return (
    <section className={"imp-panel imp-ocr-run card" + (paused ? " is-paused" : "")}>
      <div className="imp-ocr-run-head">
        <span className={"imp-panel-icon" + (paused ? " is-warn" : "")} aria-hidden="true"><Icon name={paused ? "pause" : "cpu"} size={16} /></span>
        <b className="grow">{IMPORT_STATUS_LABEL[job.status] || "Reading pages…"}</b>
        {p.total ? <span className="imp-ocr-count">{p.done}/{p.total} pages</span> : null}
      </div>
      <div className="imp-ocr-figure" aria-hidden="true">
        <span className="imp-ocr-pct">{pct}</span><span className="imp-ocr-unit">%</span>
      </div>
      <div className="imp-foreedge" role="progressbar" aria-label="OCR progress"
           aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        {Array.from({ length: EDGE_PAGES }, (_, i) => (
          <i key={i} className={i < lit ? "is-lit" : i === lit && !paused && p.total ? "is-next" : ""} style={{ "--i": i }} />
        ))}
      </div>
      {paused && (
        <p className="imp-panel-note">
          Gemini's daily free quota is used up. This resumes automatically tomorrow — no pages are re-read.
        </p>
      )}
    </section>
  );
}

const WORKING_NOTE = {
  receiving: "Receiving the file.", uploaded: "Waiting for an import worker to pick this book up.",
  parsing: "Reading the book's structure.", segmenting: "Finding the chapter breaks.",
  committing: "Adding the chapters to your library.", commit_running: "Adding the chapters to your library.",
  ocr_pending: "Waiting for the OCR worker.",
};

export function WorkingState({ job }) {
  return (
    <section className="imp-panel imp-working card" role="status">
      <svg className="imp-working-wave" viewBox="0 0 120 24" aria-hidden="true" focusable="false">
        <path className="imp-working-path" d="M2 12Q17 2 32 12T62 12T92 12T118 12" />
        <path className="imp-working-glint" d="M2 12Q17 2 32 12T62 12T92 12T118 12" />
      </svg>
      <div className="grow">
        <b className="imp-working-title">{IMPORT_STATUS_LABEL[job.status] || "Working…"}</b>
        <p className="imp-working-stage">{job.stage || WORKING_NOTE[job.status] || "Working on it."}</p>
        <p className="imp-panel-note">This keeps going in the background — you can leave this page.</p>
      </div>
    </section>
  );
}

export function CommittedState({ title, onOpen }) {
  return (
    <section className="imp-panel imp-done card">
      <span className="imp-done-orb" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M6 12.5l4 4 8-9" /></svg>
      </span>
      <div className="grow">
        <b className="imp-done-title">Imported into your library.</b>
        <p className="imp-panel-note">{title} is on your shelf now.</p>
      </div>
      <Button variant="primary" iconRight="arrowRight" onClick={onOpen}>Open novel</Button>
    </section>
  );
}

export function ErrorState({ job, onDelete }) {
  const failed = job.status === "failed";
  return (
    <section className="imp-panel imp-error card">
      <span className="imp-panel-icon is-danger" aria-hidden="true"><Icon name="alert" size={16} /></span>
      <div className="imp-error-body">
        <b className="imp-error-title">{failed ? "This import stopped" : "The last attempt hit a problem"}</b>
        {job.error
          ? <pre className="imp-error-text">{job.error}</pre>
          : <p className="imp-panel-note">The import worker didn't report a reason.</p>}
        {failed && <p className="imp-panel-note">Fix the file and upload it again, or remove this import.</p>}
      </div>
      {failed && onDelete && (
        <Button variant="ghost" size="sm" icon="trash" className="is-danger imp-error-action" onClick={onDelete}>Delete import</Button>
      )}
    </section>
  );
}
