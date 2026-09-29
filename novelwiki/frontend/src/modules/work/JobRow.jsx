/* One canonical job/activity row — kind glyph, status orb, live progress,
   relative time, cancel. Used by the Jobs page and the novel Manage tab.
   Props: job, onCancel, onOpenNovel, busy, detail (the error is shown by
   the caller, not inline). Optional: expanded + onToggle (a disclosure for
   failed rows), duration (how long a finished job took). The row lays itself
   out by its own width (container queries), so it fits any column. */
import React, { useRef } from "react";
import { Icon } from "../../components/Icon.jsx";
import { Chip, ProgressBar, RelativeTime, IconButton } from "../../components/ui.jsx";
import { ACT_KIND_LABEL, ACT_KIND_ICON, activityProgress, activityFraction } from "../../lib/constants.js";

const PHASE = {
  running: "working", generating: "working", parsing: "working", segmenting: "working",
  committing: "working", commit_running: "working", receiving: "working", ocr_running: "working",
  queued: "queued", uploaded: "queued", ocr_pending: "queued",
  waiting_provider: "waiting", ocr_paused: "waiting",
  awaiting_review: "attention", awaiting_ocr_confirm: "attention",
  done: "done", committed: "done", failed: "failed", canceled: "canceled",
};
const STATUS_LABEL = {
  queued: "Queued", running: "Running", generating: "Generating", parsing: "Parsing",
  segmenting: "Segmenting", committing: "Committing", commit_running: "Committing",
  receiving: "Receiving", uploaded: "Uploaded", ocr_pending: "OCR queued", ocr_running: "Reading pages",
  ocr_paused: "OCR paused", waiting_provider: "Waiting on provider", awaiting_review: "Ready to review",
  awaiting_ocr_confirm: "Needs OCR approval", done: "Done", committed: "Committed", failed: "Failed", canceled: "Canceled",
};

const GENERIC_PROGRESS = new Set(["narrating…", "Waiting to begin"]);

/** working · queued · waiting · attention · done · failed · canceled · idle */
export function jobPhase(status) {
  return PHASE[status] || "idle";
}

export function jobStatusLabel(status) {
  const text = String(status || "").replace(/_/g, " ");
  return STATUS_LABEL[status] || (text.charAt(0).toUpperCase() + text.slice(1));
}

export function JobRow({ job, onCancel, onOpenNovel, busy, detail, expanded, onToggle, duration }) {
  const kindLabel = ACT_KIND_LABEL[job.kind] || job.kind;
  const phase = jobPhase(job.status);
  const firstPhase = useRef(phase);
  const frac = activityFraction(job);
  const active = !!job.cancelable;
  const progressText = activityProgress(job);
  // The shared helper falls back to in-progress phrases ("narrating…") and, for
  // imports, the raw status. A finished row shows only real progress or its file.
  const settled = phase === "done" || phase === "failed" || phase === "canceled";
  const generic = progressText === job.status || (settled && GENERIC_PROGRESS.has(progressText));
  const desc = (progressText && !generic ? progressText : "") || job.filename || "";
  const failed = job.status === "failed" && !!job.error;
  const showProgress = frac != null && active;
  return (
    <div className={`job-row jr is-${phase}`} data-kind={job.kind}>
      <div className="jr-grid">
        <span className="jr-glyph" aria-hidden="true">
          <Icon name={ACT_KIND_ICON[job.kind] || "sparkles"} size={16} />
        </span>
        <div className="jr-main">
          <div className="jr-top">
            <span className="jr-kind">{kindLabel}</span>
            <span className="jr-status">
              <span key={phase} className={"jr-orb" + (phase !== firstPhase.current ? " is-settling" : "")} aria-hidden="true" />
              {jobStatusLabel(job.status)}
            </span>
            {job.execution_backend && (
              <Chip tone={job.execution_backend === "agy" ? "accent" : "neutral"} className="mono jr-backend">
                {job.backend_fallback_from
                  ? `${job.backend_fallback_from.toUpperCase()}→${job.execution_backend.toUpperCase()}`
                  : job.execution_backend.toUpperCase()}
              </Chip>
            )}
          </div>
          {desc && <p className="jr-desc">{desc}</p>}
          {failed && !detail && <p className="jr-err" title={job.error}>{(job.error || "").slice(0, 60)}</p>}
          {((job.attempts > 1 && job.status !== "done") || duration) && (
            <p className="jr-meta">
              {job.attempts > 1 && job.status !== "done" && <span>attempt {job.attempts}/{job.max_attempts}</span>}
              {duration && <span>took {duration}</span>}
            </p>
          )}
        </div>
        {showProgress && (
          <div className="jr-progress">
            <ProgressBar live={phase === "working"} size="sm" value={frac * 100} label={`${kindLabel} progress`} />
            <span className="jr-pct">{Math.round(frac * 100)}%</span>
          </div>
        )}
        <div className="jr-aside">
          <span className="jr-time"><RelativeTime iso={job.updated_at || job.created_at} /></span>
          <span className="jr-actions">
            {job.novel_id && onOpenNovel && (
              <IconButton plain name="book" size={15} label="Open novel" onClick={() => onOpenNovel(job.novel_id)} />
            )}
            {active && onCancel && (
              <IconButton plain name="x" size={15} label="Cancel" disabled={busy} onClick={() => onCancel(job)} />
            )}
            {failed && onToggle && (
              <button type="button" className={"icon-btn plain jr-disclose" + (expanded ? " is-open" : "")}
                      aria-expanded={!!expanded} aria-label={expanded ? "Hide error" : "Show error"}
                      title={expanded ? "Hide error" : "Show error"} onClick={onToggle}>
                <Icon name="chevronDown" size={16} />
              </button>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}
