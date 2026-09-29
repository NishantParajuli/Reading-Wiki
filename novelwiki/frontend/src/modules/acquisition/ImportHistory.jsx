/* Recent imports — a shelf of uploads with status dots, series selection
   and a sliding selection light. */
import React, { useId } from "react";

import { Icon } from "../../components/Icon.jsx";
import { Button, Cover, Skeleton } from "../../components/ui.jsx";
import { AnimatePresence, motion, springs } from "../../motion/index.js";
import { IMPORT_STATUS_LABEL, importTitle, importTone } from "./importStatus.js";

const slide = {
  initial: { height: 0, opacity: 0 },
  animate: { height: "auto", opacity: 1, transition: { height: springs.smooth, opacity: { duration: 0.28 } } },
  exit: { height: 0, opacity: 0, transition: { duration: 0.2 } },
};

export function ImportHistory({ jobs, jobsError, loadJobs, sel, setSel, seriesCount,
  seriesSel, setSeriesSel, seriesTarget, setSeriesTarget, novelChoices,
  busy, seriesBlocked, commitSeriesNow, setDeleteTarget }) {
  const uid = useId();
  return (
    <section className="imp-history" aria-labelledby={`${uid}-title`}>
      <div className="imp-history-head">
        <h2 id={`${uid}-title`} className="imp-side-title">Recent imports</h2>
        {jobs && jobs.length > 0 && <span className="imp-history-count">{jobs.length}</span>}
      </div>
      <AnimatePresence initial={false}>
        {seriesCount >= 2 && (
          <motion.div key="series" className="imp-series-clip" {...slide}>
            <div className="imp-series">
              <div className="imp-series-top">
                <span className="imp-series-stack" aria-hidden="true"><Icon name="layers" size={15} /></span>
                <span className="grow"><b>{seriesCount} volumes</b> <span className="imp-series-hint">selected as one series</span></span>
              </div>
              <select className="input" value={seriesTarget}
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
              {seriesBlocked && <span role="status" className="imp-series-wait">Wait for the selected import to finish loading.</span>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {jobsError ? (
        <div className="imp-history-state" role="alert">
          <Icon name="alert" size={18} />
          <p><b>Imports couldn't load</b>{jobsError}</p>
          <Button variant="ghost" size="sm" icon="refresh" onClick={loadJobs}>Try again</Button>
        </div>
      ) : jobs == null ? (
        <div className="imp-list" aria-busy="true">
          <span className="sr-only" role="status">Loading…</span>
          {[0, 1, 2].map(i => (
            <div key={i} className="imp-item is-skeleton" aria-hidden="true">
              <Skeleton variant="cover" width={30} />
              <div className="grow"><Skeleton variant="text" width="70%" /><Skeleton variant="text" width="42%" style={{ marginTop: 8 }} /></div>
            </div>
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="imp-history-state is-empty">
          <p><b>No imports yet.</b>Books you upload will appear here.</p>
        </div>
      ) : (
        <ul className="imp-list">
          {jobs.map((j, i) => {
            const title = importTitle(j);
            const tone = importTone(j.status);
            const active = sel === j.id;
            return (
              <li key={j.id} className={"imp-item" + (active ? " is-active" : "") + ` tone-${tone}`} style={{ "--i": Math.min(i, 10) }}>
                {active && <motion.span layoutId={`${uid}-glow`} className="imp-item-glow" transition={springs.layout} aria-hidden="true" />}
                <button type="button" className="imp-item-select" aria-pressed={active}
                        disabled={busy} onClick={() => setSel(j.id)}>
                  <span className="imp-item-title">{title}</span>{" "}
                  <span className="imp-item-status">
                    <i className="imp-dot" aria-hidden="true" />
                    {(IMPORT_STATUS_LABEL[j.status] || j.status)
                      + ((j.detected_meta && j.detected_meta.series) ? " · " + j.detected_meta.series : "")}
                  </span>
                </button>
                {/* After the title in the DOM (shown first via CSS order), so text lookups land on the title. */}
                <span className="imp-item-cover" aria-hidden="true">
                  <Cover src={j.detected_meta && j.detected_meta.cover_url} title={title} />
                </span>
                {j.status === "awaiting_review" && (
                  <label className="check imp-item-check" title="Select for a series commit">
                    <input type="checkbox"
                           aria-label={`Select ${j.detected_meta?.title || j.filename || `import ${j.id}`} for a series`}
                           checked={!!seriesSel[j.id]}
                           onClick={e => e.stopPropagation()}
                           onChange={e => setSeriesSel(prev => ({ ...prev, [j.id]: e.target.checked }))} />
                  </label>
                )}
                <button type="button" className="icon-btn plain imp-item-delete" title="Delete" aria-label="Delete import"
                        disabled={busy} onClick={() => setDeleteTarget(j)}>
                  <Icon name="trash" size={14} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
