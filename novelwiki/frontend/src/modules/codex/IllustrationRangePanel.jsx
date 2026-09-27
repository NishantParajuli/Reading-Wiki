import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../components/ui.jsx";
import { Icon } from "../../components/Icon.jsx";
import { codexApi } from "./api.js";
import { ILLUSTRATION_STYLES } from "./ChapterIllustrations.jsx";

const ACTIVE = new Set(["queued", "running", "waiting_provider"]);

export function IllustrationRangePanel({ novelId, novel }) {
  const id = useId();
  const [from, setFrom] = useState(String(novel.progress?.last_chapter ?? novel.min_chapter ?? 1));
  const [through, setThrough] = useState("");
  const [style, setStyle] = useState("luminous");
  const [force, setForce] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const revision = useRef(0);
  const inFlight = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; revision.current += 1; }; }, []);
  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const request = ++revision.current;
    try {
      const result = await codexApi.illustrationRange(novelId);
      if (alive.current && request === revision.current) { setData(result); setError(null); }
    } catch (failure) {
      if (alive.current && request === revision.current) setError(failure.message || "Illustration availability couldn’t load. Try again.");
    } finally { inFlight.current = false; }
  }, [novelId]);
  useEffect(() => { load(); }, [load]);
  const job = data?.active_job;
  const active = ACTIVE.has(job?.status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [active, load]);

  async function generate(event) {
    event.preventDefault();
    if (busy || active || !data?.can_generate) return;
    const first = Number(from), last = Number(through);
    if (!from.trim() || !through.trim() || !Number.isFinite(first) || !Number.isFinite(last) || first > last) {
      setError("Enter a first and final chapter, with the final chapter at or after the first."); return;
    }
    setBusy(true); setError(null); revision.current += 1;
    try {
      const result = await codexApi.generateIllustrationRange(novelId, { from_chapter: first, to_chapter: last, style, force });
      if (!alive.current) return;
      setData(current => ({ ...current, active_job: { id: result.job_id, status: "queued" } }));
    } catch (failure) { if (alive.current) setError(failure.message || "Illustration generation couldn’t start. Try again."); }
    finally { if (alive.current) setBusy(false); }
  }

  return <section className="card manage-card manage-span illustration-range" aria-labelledby={`${id}-heading`}>
    <h3 id={`${id}-heading`}><Icon name="sparkles" size={16} /> Illustrate ahead</h3>
    <p className="muted">Prepare illustrations before you read. AI chooses one to three scenes per chapter and places them where they belong in the story.</p>
    <form onSubmit={generate}>
      <div className="chapter-art-fields">
        <label htmlFor={`${id}-from`}>From chapter<input id={`${id}-from`} type="number" step="any" required value={from} disabled={busy || active} onChange={event => setFrom(event.target.value)} /></label>
        <label htmlFor={`${id}-through`}>Through chapter<input id={`${id}-through`} type="number" step="any" required value={through} disabled={busy || active} onChange={event => setThrough(event.target.value)} placeholder="100" /></label>
        <label htmlFor={`${id}-style`}>Art style<select id={`${id}-style`} value={style} disabled={busy || active} onChange={event => setStyle(event.target.value)}>{ILLUSTRATION_STYLES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <Button type="submit" icon="sparkles" loading={busy} disabled={!data?.can_generate || active}>{busy ? "Starting…" : "Illustrate chapters"}</Button>
      </div>
      <label className="illustration-range-replace"><input type="checkbox" checked={force} disabled={busy || active} onChange={event => setForce(event.target.checked)} /> Generate again for chapters that already have this art style</label>
      <p className="chapter-art-note">Existing illustrations are skipped by default. Chapters run in order so character designs carry forward. You can leave this screen while they finish.</p>
    </form>
    {active && <div className="chapter-art-progress" role="status"><span className="btn-spinner" aria-hidden /><span>{job.status === "waiting_provider" ? "Waiting for image generation to become available." : job.progress?.stage || job.stage || "Your chapters are queued for illustration."}</span><Link to="/jobs">View progress in Jobs</Link></div>}
    {job?.status === "done" && <p className="chapter-art-note" role="status">Illustrations are ready in the reader. <Link to="/jobs">View job details</Link></p>}
    {job?.status === "failed" && <p className="chapter-art-error" role="alert">{job.error || "Generation stopped. Completed chapters are kept; retry to continue."} <Link to="/jobs">View job details</Link></p>}
    {job?.status === "canceled" && <p className="chapter-art-note" role="status">Generation canceled. Completed illustrations are kept.</p>}
    {data === null && !error && <p className="chapter-art-note" role="status">Checking illustration availability…</p>}
    {data && !data.can_generate && <p className="chapter-art-note">{data.unavailable_reason || "Illustrations require an available Codex account."}</p>}
    {error && <div className="chapter-art-error" role="alert"><p>{error}</p><Button variant="ghost" size="sm" onClick={() => { setError(null); load(); }}>Refresh availability</Button></div>}
  </section>;
}
