import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Loading } from "../../components/ui.jsx";
import { Icon } from "../../components/Icon.jsx";
import { AnimatePresence, motion } from "../../motion/index.js";
import { codexApi } from "./api.js";
import { useReducedMotionPref } from "./parts.jsx";
import "./ChapterIllustrations.css";

const ACTIVE = new Set(["queued", "running", "waiting_provider"]);
const STATUS = { queued: "Waiting to begin", running: "Creating your illustrations", waiting_provider: "Waiting for image generation to become available" };
export const ILLUSTRATION_STYLES = [
  { value: "luminous", label: "Luminous anime", description: "Expressive anime characters, clean linework, soft cel shading, and luminous light." },
  { value: "painterly", label: "Painterly", description: "Semi-realistic characters, textured brushwork, and cinematic lighting." },
];

/* Art style picker: a real <select> (keyboard, screen readers, native mobile
   sheets) dressed with a small swatch of the chosen style. */
export function StylePicker({ id, value, onChange, disabled, describedBy }) {
  return (
    <label className="chapter-art-style" htmlFor={id}>
      <span className="chapter-art-style-label">Art style</span>
      <span className="chapter-art-style-control">
        <span className={`chapter-art-swatch is-${value}`} aria-hidden="true" />
        <select id={id} aria-describedby={describedBy} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
          {ILLUSTRATION_STYLES.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <Icon name="chevronDown" size={15} sw={2} className="chapter-art-style-chev" />
      </span>
    </label>
  );
}

/* A framed plate: matted image (fades in from blur once loaded), italic
   caption beneath. Inside the reader it inherits the reading font and tone. */
export function Illustration({ item, inline = false }) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const imgRef = useRef(null);
  useEffect(() => {
    const img = imgRef.current;
    if (img && img.complete && img.naturalWidth > 0) setLoaded(true);
  }, []);
  const title = item.title || (item.kind === "reference" ? "Character reference" : "Chapter illustration");
  return (
    <figure className={"chapter-art" + (inline ? " chapter-art-inline" : "") + (item.kind === "reference" ? " is-reference" : "")}>
      {failed ? <div className="chapter-art-missing" role="status"><Icon name="image" size={18} /><span>This image couldn’t load. <a href={item.image_url} target="_blank" rel="noreferrer">Open image</a></span></div>
        : <a className={"chapter-art-image" + (loaded ? " is-loaded" : "")} href={item.image_url} target="_blank" rel="noreferrer" aria-label={`Open ${item.title || "illustration"} at full size`}>
          <img ref={imgRef} src={item.image_url} alt={item.caption || item.title || "Generated chapter illustration"} loading="lazy" decoding="async"
               onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
          <span className="chapter-art-open" aria-hidden="true"><Icon name="arrowUpRight" size={14} sw={2} /></span>
        </a>}
      <figcaption>
        <span className="chapter-art-title">{title}</span>
        {item.caption && <span className="chapter-art-caption">{item.caption}</span>}
        {item.design_notes && <details className="chapter-art-notes"><summary>Design notes</summary><span className="chapter-art-notes-body">{item.design_notes}</span></details>}
      </figcaption>
    </figure>
  );
}

function IllustrationPanel({ novelId, chapter, children, personalVersion }) {
  const panelId = useId();
  const reduced = useReducedMotionPref();
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

  const hint = active ? "In progress" : scenes.length ? `${scenes.length} ${scenes.length === 1 ? "scene" : "scenes"}` : null;
  const stageText = active ? (job.status === "running" ? job.progress?.stage || job.stage || STATUS.running : STATUS[job.status]) : null;

  return (
    <>
    {children?.(personalVersion ? [] : scenes)}
    <section className={"chapter-illustrations" + (open ? " is-open" : "")} aria-label="Chapter illustrations">
      <h2 className="chapter-illustrations-heading">
        <button type="button" className="chapter-illustrations-toggle" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(value => !value)}>
          <span className="chapter-illustrations-orb" aria-hidden="true"><Icon name="wand" size={19} /></span>
          <span className="chapter-illustrations-copy">
            <span className="chapter-illustrations-title">Illustrate this chapter</span>
            <span className="chapter-illustrations-subtitle">AI-chosen scenes & character sheets</span>
          </span>
          {hint && <span className={"chapter-illustrations-hint" + (active ? " is-active" : "")}>{active && <i aria-hidden="true" />}{hint}</span>}
          <Icon name="chevronDown" size={20} className={"chapter-illustrations-chev" + (open ? " is-open" : "")} />
        </button>
      </h2>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div id={panelId} key="body" className="chapter-illustrations-body"
                      initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                      transition={reduced ? { duration: 0 } : { height: { type: "spring", stiffness: 260, damping: 34 }, opacity: { duration: 0.28 } }}>
            <div className="chapter-illustrations-inner">
              {data === null && loading && <Loading label="Opening illustrations…" />}
              {error && <div className="chapter-art-error" role="alert"><Icon name="circleAlert" size={17} /><p>{error}</p><Button variant="ghost" size="sm" icon="refresh" onClick={load} loading={loading}>Refresh illustrations</Button></div>}
              {data && <>
                <p className="chapter-illustrations-intro">AI chooses one to three scenes and places each illustration in the story. Character sheets help keep recurring faces consistent; imagined details may differ from yours.</p>
                {!data.can_generate && <div className="chapter-art-fields">
                  <StylePicker id={`${panelId}-gallery-style`} describedBy={`${panelId}-style-description`} value={style} onChange={setStyle} />
                </div>}
                {!data.can_generate && <p id={`${panelId}-style-description`} className="chapter-art-note">{styleDescription}</p>}
                {personalVersion && scenes.length > 0 && <p className="chapter-art-note">Illustrations follow the shared chapter. Switch to the shared version to see them in the story.</p>}
                {references.length > 0 && <details className="chapter-art-references"><summary>Character reference sheets <span>({references.length})</span></summary>
                  <div className="chapter-art-reference-grid">{references.map(item => <Illustration key={item.id} item={item} />)}</div>
                </details>}
                {earlierIllustrations.length > 0 && <details className="chapter-art-references"><summary>Earlier illustrations <span>({earlierIllustrations.length})</span></summary>
                  <p className="chapter-art-note">These images use styles that are no longer available for generation.</p>
                  <div className="chapter-art-reference-grid">{earlierIllustrations.map(item => <Illustration key={item.id} item={item} />)}</div>
                </details>}
                {active && <div className="chapter-art-progress" role="status">
                  <span className="spinner" aria-hidden="true" />
                  <span className="chapter-art-progress-copy">
                    <span>{stageText}. You can keep reading.</span>
                    <span className="chapter-art-progress-line" aria-hidden="true"><i /></span>
                  </span>
                  <Link to="/jobs">View jobs</Link>
                </div>}
                {job?.status === "failed" && <p className="chapter-art-error" role="alert"><Icon name="circleAlert" size={17} /><span>{job.error || "Illustration generation failed. You can try again."} <Link to="/jobs">View jobs</Link></span></p>}
                {job?.status === "canceled" && <p className="chapter-art-note" role="status">Illustration generation was canceled.</p>}
                {data.can_generate ? <form className="chapter-art-form" onSubmit={generate}>
                  <div className="chapter-art-fields">
                    <StylePicker id={`${panelId}-style`} describedBy={`${panelId}-style-description`} value={style} disabled={busy || active} onChange={setStyle} />
                    <Button type="submit" icon="sparkles" loading={busy} disabled={active || loading}>{busy ? "Starting…" : scenes.length ? "Generate again" : "Generate illustrations"}</Button>
                  </div>
                  <p id={`${panelId}-style-description`} className="chapter-art-note">{styleDescription}</p>
                  <p className="chapter-art-note">New character sheets are created before chapter scenes, so early chapters can take longer. Generation uses the connected Codex account. {scenes.length ? "Generate again creates a new set of scenes." : "Nothing is generated until you choose to begin."}</p>
                </form> : !active && <p className="chapter-art-note chapter-art-unavailable"><Icon name="lock" size={14} /> {data.unavailable_reason || "Illustration generation isn’t available for this chapter or account."}</p>}
              </>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
    </>
  );
}

// Remount on navigation so no image or in-flight result crosses a chapter boundary.
export function ChapterIllustrations({ novelId, chapter, children, personalVersion }) {
  return <IllustrationPanel key={`${novelId}:${chapter}`} novelId={novelId} chapter={chapter} personalVersion={personalVersion}>{children}</IllustrationPanel>;
}
