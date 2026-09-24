import React from "react";
import { Icon } from "../../components/Icon.jsx";
import { Button, EmptyState, Loading } from "../../components/ui.jsx";
import { IMPORT_STATUS_LABEL } from "./ImportParts.jsx";

export function ImportHistory({ jobs, jobsError, loadJobs, sel, setSel, seriesCount,
  seriesSel, setSeriesSel, seriesTarget, setSeriesTarget, novelChoices,
  busy, seriesBlocked, commitSeriesNow, setDeleteTarget }) {
  return (
    <div>
      <h2 className="section-title">Recent imports</h2>
      {seriesCount >= 2 && (
        <div className="card" style={{ padding: "8px 10px", marginBottom: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span className="grow" style={{ fontSize: "var(--text-sm)" }}>{seriesCount} selected</span>
          <select className="input" style={{ width: "auto", minWidth: 150 }} value={seriesTarget}
                  aria-label="Series destination"
                  onChange={e => setSeriesTarget(e.target.value)}>
            <option value="">Create new novel</option>
            {novelChoices.map(novel => (
              <option key={novel.id} value={novel.id}>Append to {novel.title}</option>
            ))}
          </select>
          <Button variant="primary" size="sm" icon="layers" loading={busy} disabled={seriesBlocked} onClick={commitSeriesNow}>
            {seriesTarget ? "Append volumes" : "Commit as series"}
          </Button>
          {seriesBlocked && <span role="status" className="muted">Wait for the selected import to finish loading.</span>}
        </div>
      )}
      {jobsError ? (
        <EmptyState icon="alert" title="Imports couldn't load" body={jobsError}
          primaryAction={<Button variant="ghost" onClick={loadJobs}>Try again</Button>} />
      ) : jobs == null ? (
        <Loading label="Loading…" />
      ) : jobs.length === 0 ? (
        <div className="muted" style={{ fontSize: "var(--text-sm)", padding: 8 }}>No imports yet.</div>
      ) : (
        <div className="card" style={{ padding: 6 }}>
          {jobs.map(j => (
            <div key={j.id} className={"import-job-row" + (sel === j.id ? " active" : "")}>
              {j.status === "awaiting_review" && (
                <input type="checkbox" title="Select for a series commit"
                       aria-label={`Select ${j.detected_meta?.title || j.filename || `import ${j.id}`} for a series`}
                       checked={!!seriesSel[j.id]}
                       onClick={e => e.stopPropagation()}
                       onChange={e => setSeriesSel(prev => ({ ...prev, [j.id]: e.target.checked }))} />
              )}
              <button type="button" className="import-job-select grow" aria-pressed={sel === j.id}
                      disabled={busy} onClick={() => setSel(j.id)}
                      style={{ minWidth: 0, padding: "6px 0", textAlign: "left", color: "inherit", font: "inherit", border: 0, background: "transparent" }}>
                <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }} className="truncate">
                  {(j.detected_meta && j.detected_meta.title) || j.filename || `Job ${j.id}`}
                </div>
                <div className="muted" style={{ fontSize: "var(--text-xs)" }}>
                  {(IMPORT_STATUS_LABEL[j.status] || j.status)
                    + ((j.detected_meta && j.detected_meta.series) ? " · " + j.detected_meta.series : "")}
                </div>
              </button>
              <button className="icon-btn plain" title="Delete" aria-label="Delete import"
                      disabled={busy} onClick={() => setDeleteTarget(j)}>
                <Icon name="x" size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
