/* The selected import: tideline, book header, and whichever step needs the
   reader now (OCR approval, progress, review, the finished book). */
import React, { useEffect, useRef } from "react";

import { Icon } from "../../components/Icon.jsx";
import { Skeleton } from "../../components/ui.jsx";
import { useBookAtmosphere } from "../../atmosphere/store.js";
import { prefersReducedMotion } from "../../motion/navigation.js";
import {
  CommittedState, ErrorState, JobHeader, OcrConfirm, OcrProgress, PlanEditor, Stepper, WorkingState,
} from "./ImportParts.jsx";
import { IMPORT_BUSY, importTitle } from "./importStatus.js";

const WELCOME = [
  { icon: "upload", title: "Upload", body: "EPUBs and PDFs, one or many. Scanned PDFs wait for your go-ahead before OCR runs." },
  { icon: "edit", title: "Review", body: "Check chapter breaks, numbering and book details. Nothing is added to your library yet." },
  { icon: "check", title: "Commit", body: "Create a new novel, append to one you can edit, or replace a source's chapters." },
];

function Welcome() {
  return (
    <section className="imp-welcome card">
      <p className="imp-eyebrow">Select an import</p>
      <h2 className="imp-welcome-title">Upload an EPUB or pick a recent import to review it.</h2>
      <ol className="imp-welcome-steps">
        {WELCOME.map((step, i) => (
          <li key={step.title} style={{ "--i": i }}>
            <span className="imp-welcome-orb" aria-hidden="true"><Icon name={step.icon} size={17} /></span>
            <b>{step.title}</b>
            <p>{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Opening() {
  return (
    <div className="imp-opening card" role="status">
      <Skeleton variant="cover" width={72} />
      <div className="imp-opening-lines">
        <Skeleton variant="text" width="34%" />
        <Skeleton variant="text" width="72%" height={22} />
        <Skeleton variant="text" width="46%" />
        <span className="imp-opening-label">Opening import…</span>
      </div>
    </div>
  );
}

export function ImportDetail({
  sel, job, jobError, plan, setPlan, metadata, setMetadata, novelChoices, busy, reviewReady,
  onSave, onCommit, onConfirmOcr, onOpenNovel, onDelete,
}) {
  const ref = useRef(null);
  const loaded = !!job && job.id === sel;
  useBookAtmosphere(loaded ? {
    id: `import:${job.id}`, cover_url: (job.detected_meta && job.detected_meta.cover_url) || null, title: importTitle(job),
  } : null);

  // On one-column layouts the detail sits below the list: once the chosen
  // import has loaded (and the page is tall enough), bring it into view.
  const shownFor = useRef(null);
  const loadedId = loaded ? job.id : null;
  useEffect(() => {
    if (sel == null) { shownFor.current = null; return; }
    const el = ref.current;
    if (loadedId == null || shownFor.current === loadedId || !el) return;
    shownFor.current = loadedId;
    if (typeof el.scrollIntoView !== "function" || !window.matchMedia) return;
    if (!window.matchMedia("(max-width: 959px)").matches) return;
    if (el.getBoundingClientRect().top > window.innerHeight * 0.45) {
      el.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
    }
  }, [sel, loadedId]);

  const meta = { ...(job?.detected_meta || {}), ...(metadata || {}) };
  const committedNovel = job && job.status === "committed" && job.novel_id;
  let body = null;
  if (job) {
    if (job.status === "awaiting_ocr_confirm") body = <OcrConfirm job={job} onConfirm={onConfirmOcr} busy={busy} />;
    else if (["ocr_pending", "ocr_running", "ocr_paused"].includes(job.status)) body = <OcrProgress job={job} />;
    else if (job.status === "awaiting_review" && reviewReady) {
      body = (
        <PlanEditor key={job.id} job={{ ...job, _novels: novelChoices }}
                    plan={plan} setPlan={setPlan}
                    metadata={metadata} setMetadata={setMetadata}
                    onSave={onSave} onCommit={onCommit} busy={busy} />
      );
    } else if (IMPORT_BUSY.includes(job.status)) body = <WorkingState job={job} />;
  }

  return (
    <div className="imp-detail" ref={ref}>
      {jobError && (
        <div role="alert" className="imp-retry"><Icon name="refresh" size={14} className="spin" />{jobError} Retrying automatically…</div>
      )}
      {sel != null && !loaded ? <Opening /> : job == null ? <Welcome /> : (
        <div className="imp-flow" key={job.id}>
          <Stepper job={job} />
          <JobHeader job={job} meta={meta} />
          {(job.error || job.status === "failed") && <ErrorState job={job} onDelete={() => onDelete(job)} />}
          {committedNovel && <CommittedState title={meta.title || importTitle(job)} onOpen={() => onOpenNovel(job.novel_id)} />}
          {body}
        </div>
      )}
    </div>
  );
}
