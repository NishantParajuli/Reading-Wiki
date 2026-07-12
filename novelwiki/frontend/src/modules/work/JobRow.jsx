/* One canonical job/activity row — kind icon, status chip, live progress,
   relative time, cancel. Used by Home's activity strip, the Jobs page, and
   the novel Manage tab (replaces the two colliding ActivityRow components). */
import React from "react";
import { Icon } from "../../components/Icon.jsx";
import { Chip, ProgressBar, RelativeTime, IconButton } from "../../components/ui.jsx";
import { ACT_KIND_LABEL, ACT_KIND_ICON, ACT_STATUS_TONE, activityProgress, activityFraction } from "../../lib/constants.js";

export function JobRow({ job, onCancel, onOpenNovel, busy, detail }) {
  const kindLabel = ACT_KIND_LABEL[job.kind] || job.kind;
  const tone = ACT_STATUS_TONE[job.status] || "neutral";
  const frac = activityFraction(job);
  const active = !!job.cancelable;
  return (
    <div className="job-row">
      <span className="job-kind">
        <Icon name={ACT_KIND_ICON[job.kind] || "sparkles"} size={15} className="muted" />
        {kindLabel}
      </span>
      {job.execution_backend && (
        <Chip tone={job.execution_backend === "agy" ? "accent" : "neutral"}>
          {job.backend_fallback_from
            ? `${job.backend_fallback_from.toUpperCase()}→${job.execution_backend.toUpperCase()}`
            : job.execution_backend.toUpperCase()}
        </Chip>
      )}
      <Chip tone={tone === "neutral" ? "neutral" : tone}>{job.status}</Chip>
      <span className="job-desc">{activityProgress(job) || job.filename || ""}</span>
      {frac != null && active && <ProgressBar className="job-progress" size="xs" value={frac * 100} />}
      {job.error && job.status === "failed" && !detail && (
        <span className="job-err" title={job.error}>{(job.error || "").slice(0, 60)}</span>
      )}
      {job.attempts > 1 && job.status !== "done" && (
        <span className="muted" style={{ fontSize: "var(--text-xs)" }}>attempt {job.attempts}/{job.max_attempts}</span>
      )}
      <span className="job-time"><RelativeTime iso={job.updated_at || job.created_at} /></span>
      {job.novel_id && onOpenNovel && (
        <IconButton plain name="book" size={15} label="Open novel" onClick={() => onOpenNovel(job.novel_id)} />
      )}
      {active && onCancel && (
        <IconButton plain name="x" size={15} label="Cancel" disabled={busy} onClick={() => onCancel(job)} />
      )}
    </div>
  );
}
