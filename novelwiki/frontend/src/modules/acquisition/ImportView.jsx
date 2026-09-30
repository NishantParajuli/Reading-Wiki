/* EPUB/PDF wizard: Upload → Parse → [OCR] → Review → Commit.
   Left: the glass basin and the shelf of recent imports.
   Right: the selected import, told as a tideline. */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { acquisitionApi } from "../../modules/acquisition/api.js";
import { catalogApi } from "../../modules/catalog/api.js";
import { useAuth } from "../../App.jsx";
import { PageHeader } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { ImportHistory } from "./ImportHistory.jsx";
import { ImportDetail } from "./ImportDetail.jsx";
import { ConfirmDialog } from "../../components/overlay.jsx";
import { useTitle } from "../../lib/hooks.js";

import {
  DuplicateWarning, FolderImport, IMPORT_BUSY, UploadDrop,
} from "../../modules/acquisition/ImportParts.jsx";

function editableMetadata(meta, jobId) {
  const source = meta || {};
  return {
    title: source.title || "",
    author: source.author || "",
    description: source.description || "",
    language: source.language || "",
    series: source.series || "",
    series_index: source.series_index == null ? "" : String(source.series_index),
    volume_label: source.volume_label || "",
    _forJob: jobId,
  };
}

function metadataPayload(metadata) {
  const text = value => String(value || "").trim() || null;
  const index = String(metadata.series_index ?? "").trim();
  return {
    title: text(metadata.title),
    author: text(metadata.author),
    description: text(metadata.description),
    language: text(metadata.language),
    series: text(metadata.series),
    series_index: index === "" ? null : Number(index),
    volume_label: text(metadata.volume_label),
  };
}

export function ImportView() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [jobs, setJobs] = useState(null);
  // The selected import lives in ?job=, so Jobs can link straight to it and a
  // reload reopens it. Choosing another import replaces the entry (no history spam).
  const [params, setParams] = useSearchParams();
  const sel = Number(params.get("job")) || null;
  const setSel = useCallback((id) => setParams(previous => {
    const next = new URLSearchParams(previous);
    if (id == null) next.delete("job"); else next.set("job", String(id));
    return next;
  }, { replace: true }), [setParams]);
  const [job, setJob] = useState(null);
  const [plan, setPlan] = useState(null);
  const [metadata, setMetadata] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dupWarn, setDupWarn] = useState(null);
  const [seriesSel, setSeriesSel] = useState({});
  const [seriesTarget, setSeriesTarget] = useState("");
  const [novelChoices, setNovelChoices] = useState([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [jobError, setJobError] = useState(null);
  const [jobsError, setJobsError] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  useTitle("Import");

  const openNovel = (id) => navigate(`/n/${id}`);

  const loadJobs = useCallback(() => {
    acquisitionApi.importJobs().then(rows => {
      setJobs(rows); setJobsError(null);
      setSeriesSel(previous => Object.fromEntries(Object.entries(previous).filter(
        ([id, selected]) => selected && rows.some(row => row.id === Number(id) && row.status === "awaiting_review"),
      )));
    }).catch(error => setJobsError(error.message || "Could not load recent imports."));
  }, []);
  useEffect(() => {
    loadJobs();
    catalogApi.novels().then(n => {
      setNovelChoices(n.filter(novel => novel.can_edit));
    }).catch(() => {});
  }, [loadJobs]);

  // Load + poll the selected job while it's being worked on server-side.
  useEffect(() => {
    if (sel == null) { setJob(null); setPlan(null); setMetadata(null); return; }
    setJobError(null);
    let cancel = false, timer = null;
    const tick = () => {
      acquisitionApi.importJob(sel).then(j => {
        if (cancel) return;
        setJobError(null);
        setJob(j);
        setPlan(prev => {
          if (j.plan && (!prev || prev._forJob !== j.id || j.status === "committed")) {
            return { ...j.plan, _forJob: j.id };
          }
          return prev;
        });
        setMetadata(prev => {
          if (!prev || prev._forJob !== j.id || j.status === "committed") {
            return editableMetadata(j.detected_meta, j.id);
          }
          return prev;
        });
        if (IMPORT_BUSY.includes(j.status)) timer = setTimeout(tick, 1500);
        else loadJobs();
      }).catch(error => {
        if (cancel) return;
        setJobError(error.message || "Could not load this import.");
        timer = setTimeout(tick, 5000);
      });
    };
    tick();
    return () => { cancel = true; if (timer) clearTimeout(timer); };
  }, [sel, loadJobs, refreshKey]);

  async function onUploaded(jobId, duplicateOf) {
    setDupWarn(duplicateOf && duplicateOf.length ? duplicateOf : null);
    loadJobs(); setSel(jobId);
  }

  const reviewReady = job?.id === sel && plan?._forJob === sel && metadata?._forJob === sel;
  const seriesBlocked = !!seriesSel[sel] && !reviewReady;

  async function commitSeriesNow() {
    const ids = Object.keys(seriesSel).filter(k => seriesSel[k]).map(Number);
    if (busy || ids.length < 2 || seriesBlocked) return;
    setBusy(true);
    try {
      if (reviewReady && ids.includes(sel)) {
        await acquisitionApi.updateImportPlan(
          sel,
          { version: plan.version || 1, segments: plan.segments },
          metadataPayload(metadata),
        );
      }
      const r = await acquisitionApi.commitSeries(
        ids, seriesTarget ? Number(seriesTarget) : null,
      );
      toast(
        seriesTarget
          ? `Appended ${ids.length} volumes to the novel.`
          : `Committed ${ids.length} volumes into one novel.`,
        { tone: "ok" },
      );
      setSeriesSel({}); setSeriesTarget(""); loadJobs();
      if (r.novel_id) openNovel(r.novel_id);
    } catch (e) { toast(e.message || "Series commit failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  }
  const seriesCount = Object.values(seriesSel).filter(Boolean).length;

  async function saveReview() {
    if (busy || !reviewReady) return;
    setBusy(true);
    try {
      await acquisitionApi.updateImportPlan(
        sel,
        { version: plan.version || 1, segments: plan.segments },
        metadataPayload(metadata),
      );
      toast("Import details saved.", { tone: "ok" });
      loadJobs();
    } catch (e) { toast(e.message || "Could not save import details.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  async function commit(body) {
    if (busy || !reviewReady) return;
    setBusy(true);
    try {
      if (plan && metadata) {
        await acquisitionApi.updateImportPlan(
          sel,
          { version: plan.version || 1, segments: plan.segments },
          metadataPayload(metadata),
        );
      }
      await acquisitionApi.commitImport(sel, body);
      setJob(previous => previous && ({ ...previous, status: "committing" }));
      setRefreshKey(key => key + 1);
      toast("Adding the book to your library…", { tone: "ok" });
    } catch (e) { toast(e.message || "Commit failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  async function confirmOcr(body) {
    setBusy(true);
    try {
      await acquisitionApi.confirmOcr(sel, body);
      setJob(previous => previous && ({ ...previous, status: "ocr_pending" }));
      setRefreshKey(key => key + 1);
      toast("OCR started…", { tone: "ok" });
    }
    catch (e) { toast(e.message || "Could not start OCR.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  async function removeJob(jid) {
    setBusy(true);
    try {
      await acquisitionApi.deleteImport(jid);
      if (sel === jid) setSel(null);
      setDeleteTarget(null);
      loadJobs();
    } catch (error) { toast(error.message || "Could not delete this import. Try again.", { tone: "danger" }); }
    finally { setBusy(false); }
  }

  return (
    <div className="page page-enter imp-page">
      <PageHeader eyebrow="Bring books aboard" title="Import a book"
        subtitle="Bring your EPUBs and PDFs into the reading room. Review chapters and book details before adding them to your library." />

      <div className="imp-layout">
        <aside className="imp-side">
          <div className="imp-side-drop rise" style={{ "--i": 3 }}>
            <UploadDrop onUploaded={onUploaded} />
            {user && user.role === "admin" && <FolderImport onQueued={loadJobs} />}
          </div>
          <div className="rise" style={{ "--i": 5 }}>
            <ImportHistory jobs={jobs} jobsError={jobsError} loadJobs={loadJobs}
              sel={sel} setSel={setSel} seriesCount={seriesCount}
              seriesSel={seriesSel} setSeriesSel={setSeriesSel}
              seriesTarget={seriesTarget} setSeriesTarget={setSeriesTarget}
              novelChoices={novelChoices} busy={busy} seriesBlocked={seriesBlocked} commitSeriesNow={commitSeriesNow}
              setDeleteTarget={setDeleteTarget} />
          </div>
        </aside>

        <div className="imp-main rise" style={{ "--i": 4 }}>
          {dupWarn && <DuplicateWarning dups={dupWarn} onOpenNovel={openNovel} />}
          <ImportDetail sel={sel} job={job} jobError={jobError}
            plan={plan} setPlan={setPlan} metadata={metadata} setMetadata={setMetadata}
            novelChoices={novelChoices} busy={busy} reviewReady={reviewReady}
            onSave={saveReview} onCommit={commit} onConfirmOcr={confirmOcr}
            onOpenNovel={openNovel} onDelete={setDeleteTarget} />
        </div>
      </div>
      {deleteTarget && <ConfirmDialog title="Delete this import?"
        body={`Remove ${deleteTarget.detected_meta?.title || deleteTarget.filename || "this import"} and its review data. Books already in your library are kept.`}
        confirmLabel="Delete import" busy={busy}
        onCancel={() => setDeleteTarget(null)} onConfirm={() => removeJob(deleteTarget.id)} />}
    </div>
  );
}
