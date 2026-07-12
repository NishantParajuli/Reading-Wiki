/* ============================================================
   Import (§6.9) — upload an EPUB/PDF, review the segmentation plan, commit.
   The multi-step nature is now a visible stepper: Upload → Parse → [OCR] →
   Review → Commit. Heavy work runs in the server-side import worker.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { acquisitionApi } from "../../modules/acquisition/api.js";
import { catalogApi } from "../../modules/catalog/api.js";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Cover, EmptyState, Loading, PageHeader, ProgressBar } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { useTitle } from "../../lib/hooks.js";

import {
  DuplicateWarning, FolderImport, IMPORT_BUSY, IMPORT_STATUS_LABEL, OcrConfirm,
  OcrProgress, PlanEditor, QualityBadge, Stepper, UploadDrop,
} from "../../modules/acquisition/ImportParts.jsx";

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
    acquisitionApi.importJobs().then(setJobs).catch(() => setJobs([]));
  }, []);
  useEffect(() => {
    loadJobs();
    catalogApi.novels().then(n => { novelsRef.current = n; }).catch(() => {});
  }, [loadJobs]);

  // Load + poll the selected job while it's being worked on server-side.
  useEffect(() => {
    if (sel == null) { setJob(null); setPlan(null); return; }
    let cancel = false, timer = null;
    const tick = () => {
      acquisitionApi.importJob(sel).then(j => {
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
      const r = await acquisitionApi.commitSeries(ids);
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
      if (plan) await acquisitionApi.updateImportPlan(sel, { version: plan.version || 1, segments: plan.segments });
      await acquisitionApi.commitImport(sel, body);
      toast("Commit started…", { tone: "ok" });
    } catch (e) { toast(e.message || "Commit failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  async function confirmOcr(body) {
    setBusy(true);
    try { await acquisitionApi.confirmOcr(sel, body); toast("OCR started…", { tone: "ok" }); }
    catch (e) { toast(e.message || "Could not start OCR.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  async function removeJob(jid) {
    await acquisitionApi.deleteImport(jid).catch(() => {});
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
