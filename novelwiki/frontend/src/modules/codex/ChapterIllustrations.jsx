import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Loading } from "../../components/ui.jsx";
import { Icon } from "../../components/Icon.jsx";
import { codexApi } from "./api.js";
import "./ChapterIllustrations.css";

const ACTIVE = new Set(["queued", "running", "waiting_provider"]);
const STATUS = { queued: "Waiting to begin", running: "Creating your illustrations", waiting_provider: "Waiting for image generation to become available" };
export const ILLUSTRATION_STYLES = [
  { value: "luminous", label: "Luminous anime", description: "Expressive anime characters, clean linework, soft cel shading, and luminous light." },
  { value: "painterly", label: "Painterly", description: "Semi-realistic characters, textured brushwork, and cinematic lighting." },
];

export function Illustration({ item, inline = false }) {
  const [failed, setFailed] = useState(false);
  return (
    <figure className={"chapter-art" + (inline ? " chapter-art-inline" : "")}>
      {failed ? <div className="chapter-art-missing" role="status">This image couldn’t load. <a href={item.image_url} target="_blank" rel="noreferrer">Open image</a></div>
        : <a className="chapter-art-image" href={item.image_url} target="_blank" rel="noreferrer" aria-label={`Open ${item.title || "illustration"} at full size`}>
          <img src={item.image_url} alt={item.caption || item.title || "Generated chapter illustration"} loading="lazy" decoding="async" onError={() => setFailed(true)} />
        </a>}
      <figcaption>
        <strong>{item.title || (item.kind === "reference" ? "Character reference" : "Chapter illustration")}</strong>
        {item.caption && <p>{item.caption}</p>}
        {item.design_notes && <details className="chapter-art-notes"><summary>Design notes</summary><p>{item.design_notes}</p></details>}
      </figcaption>
    </figure>
  );
}

function IllustrationPanel({ novelId, chapter, children, personalVersion }) {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [style, setStyle] = useState("luminous");
  const alive = useRef(true);
  const inFlight = useRef(false);
  const revision = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; revision.current += 1; }; }, []);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    const request = ++revision.current;
    setLoading(true);
    try {
      const result = await codexApi.illustrations(novelId, chapter);
      if (!alive.current || request !== revision.current) return;
      setData(result);
      setError(null);
    } catch (failure) {
      if (alive.current && request === revision.current) setError(failure.message || "Illustrations couldn’t load. Try again.");
    } finally {
      inFlight.current = false;
      if (alive.current && request === revision.current) setLoading(false);
    }
  }, [novelId, chapter]);

  useEffect(() => { if (data === null && !error) load(); }, [data, error, load]);
  const job = data?.active_job;
  const active = ACTIVE.has(job?.status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [active, load]);

  const scenes = (data?.items || []).filter(item => item.kind === "scene" && item.style === style);
  const references = (data?.items || []).filter(item => item.kind === "reference" && item.style === style);
  const earlierIllustrations = (data?.items || []).filter(item => !ILLUSTRATION_STYLES.some(option => option.value === item.style));
  const styleDescription = ILLUSTRATION_STYLES.find(option => option.value === style)?.description;

  async function generate(event) {
    event.preventDefault();
    if (busy || active || !data?.can_generate) return;
    setBusy(true); setError(null);
    // A list response that started before this action must not erase its job.
    revision.current += 1;
    try {
      const result = await codexApi.generateIllustrations(novelId, chapter, { style, force: scenes.length > 0 });
      if (!alive.current) return;
      setData(current => ({ ...current, active_job: { id: result.job_id, status: "queued" } }));
    } catch (failure) {
      if (alive.current) setError(failure.message || "Illustration generation couldn’t start. Try again.");
    } finally {
      if (alive.current) { setBusy(false); setLoading(false); }
    }
  }

  return (
    <>
    {children?.(personalVersion ? [] : scenes)}
    <section className="chapter-illustrations" aria-label="Chapter illustrations">
      <h2 className="chapter-illustrations-heading">
        <button type="button" className="chapter-illustrations-toggle" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(value => !value)}>
          <span>Illustrate this chapter<span className="chapter-illustrations-subtitle">AI-chosen scenes & character sheets</span></span>
          <Icon name="chevronDown" size={20} className={open ? "is-open" : ""} />
        </button>
      </h2>
      {open && <div id={panelId} className="chapter-illustrations-body">
        {data === null && loading && <Loading label="Opening illustrations…" />}
        {error && <div className="chapter-art-error" role="alert"><p>{error}</p><Button variant="ghost" size="sm" onClick={load} loading={loading}>Refresh illustrations</Button></div>}
        {data && <>
          <p className="chapter-illustrations-intro">AI chooses one to three scenes and places each illustration in the story. Character sheets help keep recurring faces consistent; imagined details may differ from yours.</p>
          {!data.can_generate && <div className="chapter-art-fields">
            <label htmlFor={`${panelId}-gallery-style`}>Art style<select id={`${panelId}-gallery-style`} aria-describedby={`${panelId}-style-description`} value={style} onChange={event => setStyle(event.target.value)}>
              {ILLUSTRATION_STYLES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select></label>
          </div>}
          {!data.can_generate && <p id={`${panelId}-style-description`} className="chapter-art-note">{styleDescription}</p>}
          {personalVersion && scenes.length > 0 && <p className="chapter-art-note">Illustrations follow the shared chapter. Switch to the shared version to see them in the story.</p>}
          {references.length > 0 && <details className="chapter-art-references"><summary>Character reference sheets <span>({references.length})</span></summary>
            <div className="chapter-art-reference-grid">{references.map(item => <Illustration key={item.id} item={item} />)}</div>
          </details>}
          {earlierIllustrations.length > 0 && <details className="chapter-art-references"><summary>Earlier illustrations <span>({earlierIllustrations.length})</span></summary>
            <p className="chapter-art-note">These images use styles that are no longer available for generation.</p>
            {earlierIllustrations.map(item => <Illustration key={item.id} item={item} />)}
          </details>}
          {active && <div className="chapter-art-progress" role="status"><span className="btn-spinner" aria-hidden /><span>{job.status === "running" ? job.progress?.stage || job.stage || STATUS.running : STATUS[job.status]}. You can keep reading.</span><Link to="/jobs">View jobs</Link></div>}
          {job?.status === "failed" && <p className="chapter-art-error" role="alert">{job.error || "Illustration generation failed. You can try again."} <Link to="/jobs">View jobs</Link></p>}
          {job?.status === "canceled" && <p className="chapter-art-note" role="status">Illustration generation was canceled.</p>}
          {data.can_generate ? <form className="chapter-art-form" onSubmit={generate}>
            <div className="chapter-art-fields">
              <label htmlFor={`${panelId}-style`}>Art style<select id={`${panelId}-style`} aria-describedby={`${panelId}-style-description`} value={style} disabled={busy || active} onChange={event => setStyle(event.target.value)}>
                {ILLUSTRATION_STYLES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select></label>
              <Button type="submit" icon="sparkles" loading={busy} disabled={active || loading}>{busy ? "Starting…" : scenes.length ? "Generate again" : "Generate illustrations"}</Button>
            </div>
            <p id={`${panelId}-style-description`} className="chapter-art-note">{styleDescription}</p>
            <p className="chapter-art-note">New character sheets are created before chapter scenes, so early chapters can take longer. Generation uses the connected Codex account. {scenes.length ? "Generate again creates a new set of scenes." : "Nothing is generated until you choose to begin."}</p>
          </form> : !active && <p className="chapter-art-note">{data.unavailable_reason || "Illustration generation isn’t available for this chapter or account."}</p>}
        </>}
      </div>}
    </section>
    </>
  );
}

// Remount on navigation so no image or in-flight result crosses a chapter boundary.
export function ChapterIllustrations({ novelId, chapter, children, personalVersion }) {
  return <IllustrationPanel key={`${novelId}:${chapter}`} novelId={novelId} chapter={chapter} personalVersion={personalVersion}>{children}</IllustrationPanel>;
}
