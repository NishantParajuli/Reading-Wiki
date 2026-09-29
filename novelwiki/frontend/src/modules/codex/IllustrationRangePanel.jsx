import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../../components/ui.jsx";
import { Icon } from "../../components/Icon.jsx";
import { codexApi } from "./api.js";
import { ILLUSTRATION_STYLES, StylePicker } from "./ChapterIllustrations.jsx";

const ACTIVE = new Set(["queued", "running", "waiting_provider"]);

/* Where the requested span sits in the book — only drawn when both ends are
   valid numbers inside the book's known chapter range. */
function SpanPreview({ from, through, novel }) {
  const lo = Number(novel.min_chapter ?? 1), hi = Number(novel.max_chapter);
  const a = Number(from), b = Number(through);
  if (!Number.isFinite(hi) || hi <= lo || !String(from).trim() || !String(through).trim() || !Number.isFinite(a) || !Number.isFinite(b) || a > b) return null;
  const clamp = v => Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
  const left = clamp(a), right = clamp(b);
  return (
    <div className="illustration-range-span" aria-hidden="true">
      <span className="irs-track"><span className="irs-fill" style={{ left: `${left * 100}%`, width: `${Math.max(0.8, (right - left) * 100)}%` }} /></span>
      <span className="irs-ends"><span>Ch. {lo}</span><span>Ch. {hi}</span></span>
    </div>
  );
}

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
    <span className="illustration-range-glow" aria-hidden="true" />
    <div className="illustration-range-head">
      <span className="illustration-range-orb" aria-hidden="true"><Icon name="wand" size={20} /></span>
      <div className="illustration-range-intro">
        <h3 id={`${id}-heading`} className="illustration-range-title">Illustrate ahead</h3>
        <p>Prepare illustrations before you read. AI chooses one to three scenes per chapter and places them where they belong in the story.</p>
      </div>
    </div>
    <form className="illustration-range-form" onSubmit={generate}>
      <div className="illustration-range-grid">
        <div className="illustration-range-chapters">
          <label className="illustration-range-field" htmlFor={`${id}-from`}><span>From chapter</span><input id={`${id}-from`} type="number" step="any" required value={from} disabled={busy || active} onChange={event => setFrom(event.target.value)} /></label>
          <span className="illustration-range-arrow" aria-hidden="true"><Icon name="arrowRight" size={16} sw={2} /></span>
          <label className="illustration-range-field" htmlFor={`${id}-through`}><span>Through chapter</span><input id={`${id}-through`} type="number" step="any" required value={through} disabled={busy || active} onChange={event => setThrough(event.target.value)} placeholder="100" /></label>
        </div>
        <StylePicker id={`${id}-style`} describedBy={`${id}-style-description`} value={style} disabled={busy || active} onChange={setStyle} />
        <Button type="submit" icon="sparkles" loading={busy} disabled={!data?.can_generate || active}>{busy ? "Starting…" : "Illustrate chapters"}</Button>
      </div>
      <SpanPreview from={from} through={through} novel={novel} />
      <p id={`${id}-style-description`} className="chapter-art-note">{ILLUSTRATION_STYLES.find(option => option.value === style)?.description}</p>
      <label className="check illustration-range-replace"><input type="checkbox" checked={force} disabled={busy || active} onChange={event => setForce(event.target.checked)} /> <span>Generate again for chapters that already have this art style</span></label>
      <p className="chapter-art-note">Existing illustrations are skipped by default. Chapters run in order so character designs carry forward. You can leave this screen while they finish.</p>
    </form>
    {active && <div className="chapter-art-progress" role="status"><span className="spinner" aria-hidden="true" /><span className="chapter-art-progress-copy"><span>{job.status === "waiting_provider" ? "Waiting for image generation to become available." : job.progress?.stage || job.stage || "Your chapters are queued for illustration."}</span><span className="chapter-art-progress-line" aria-hidden="true"><i /></span></span><Link to="/jobs">View progress in Jobs</Link></div>}
    {job?.status === "done" && <p className="chapter-art-note chapter-art-done" role="status"><Icon name="circleCheck" size={15} /> <span>Illustrations are ready in the reader. <Link to="/jobs">View job details</Link></span></p>}
    {job?.status === "failed" && <p className="chapter-art-error" role="alert"><Icon name="circleAlert" size={17} /><span>{job.error || "Generation stopped. Completed chapters are kept; retry to continue."} <Link to="/jobs">View job details</Link></span></p>}
    {job?.status === "canceled" && <p className="chapter-art-note" role="status">Generation canceled. Completed illustrations are kept.</p>}
    {data === null && !error && <p className="chapter-art-note" role="status"><span className="spinner" aria-hidden="true" /> Checking illustration availability…</p>}
    {data && !data.can_generate && <p className="chapter-art-note chapter-art-unavailable"><Icon name="lock" size={14} /> {data.unavailable_reason || "Illustrations require an available Codex account."}</p>}
    {error && <div className="chapter-art-error" role="alert"><Icon name="circleAlert" size={17} /><p>{error}</p><Button variant="ghost" size="sm" icon="refresh" onClick={() => { setError(null); load(); }}>Refresh availability</Button></div>}
  </section>;
}
