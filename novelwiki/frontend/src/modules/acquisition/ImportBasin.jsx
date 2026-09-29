/* ============================================================
   The glass basin — where books are dropped into Tideglass.
   A slowly flowing dashed rim (SVG stroke-dashoffset) around a vessel of
   luminous water. Dragging files over the page makes the basin glow; over
   the basin itself the water rises and ripples. While uploading, the water
   level *is* the upload progress (a gentle swell when the size is unknown).
   ============================================================ */
import React, { useEffect, useId, useRef, useState } from "react";

import { acquisitionApi } from "./api.js";
import { Chip, ProgressBar } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";

function hasFiles(event) {
  const types = event.dataTransfer && event.dataTransfer.types;
  return !!types && Array.from(types).includes("Files");
}

/* A book afloat: cover, fore-edge, crescent emblem and a ribbon. */
function BookGlyph() {
  const id = useId().replace(/:/g, "");
  return (
    <svg className="imp-glyph" viewBox="0 0 120 108" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={`${id}-cover`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" className="imp-glyph-c1" />
          <stop offset="1" className="imp-glyph-c2" />
        </linearGradient>
        <linearGradient id={`${id}-sheen`} x1="0" y1="0" x2="0.6" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.5" />
          <stop offset="0.45" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <ellipse className="imp-glyph-shadow" cx="60" cy="100" rx="28" ry="4.5" />
      <g className="imp-glyph-lift">
        <g className="imp-glyph-book">
          <rect className="imp-glyph-pages" x="37" y="16" width="51" height="72" rx="5" />
          <path className="imp-glyph-edge" d="M84.5 21v62M86.8 23v58" />
          <rect x="31" y="12" width="52" height="72" rx="5" fill={`url(#${id}-cover)`} />
          <rect className="imp-glyph-spine" x="31" y="12" width="9" height="72" rx="4" />
          <rect x="31" y="12" width="52" height="72" rx="5" fill={`url(#${id}-sheen)`} />
          <path className="imp-glyph-moon" d="M62 31a11 11 0 1 0 0 22a13 13 0 0 1 0-22z" />
          <path className="imp-glyph-title" d="M47 64h26M51 70h18" />
          <path className="imp-glyph-ribbon" d="M71 83v13l3.5-3.2 3.5 3.2V83z" />
        </g>
      </g>
    </svg>
  );
}

export function UploadDrop({ onUploaded }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [drag, setDrag] = useState(false);
  const [near, setNear] = useState(false);
  const [current, setCurrent] = useState(null);
  const inputRef = useRef(null);
  const { toast } = useToast();

  // Files dragged anywhere over the window: the basin brightens in anticipation.
  // A file dropped beside the basin is ignored instead of replacing the app.
  useEffect(() => {
    let depth = 0;
    const enter = e => { if (hasFiles(e)) { depth += 1; setNear(true); } };
    const leave = () => { depth = Math.max(0, depth - 1); if (!depth) setNear(false); };
    const over = e => { if (hasFiles(e)) e.preventDefault(); };
    const reset = e => {
      if (e && e.type === "drop" && hasFiles(e)) e.preventDefault();
      depth = 0; setNear(false); setDrag(false);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", reset);
    window.addEventListener("dragend", reset);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", reset);
      window.removeEventListener("dragend", reset);
    };
  }, []);

  async function send(input) {
    if (!input || busy) return;
    const files = Array.from(input instanceof File ? [input] : input);
    if (!files.length) return;
    const unsupported = files.filter(file => !/\.(epub|pdf)$/i.test(file.name));
    if (unsupported.length) {
      toast("Only .epub and .pdf files are supported.", { tone: "danger" });
      return;
    }
    setBusy(true); setProgress(0);
    let queued = 0;
    const failures = [];
    for (let index = 0; index < files.length; index += 1) {
      const file = files[index];
      setCurrent({ name: file.name, index, total: files.length });
      try {
        const r = await acquisitionApi.importFile(
          file,
          value => setProgress((index + value) / files.length),
        );
        queued += 1;
        onUploaded(r.id, r.duplicate_of);
      } catch (error) {
        failures.push({ file, error });
      }
    }
    if (files.length > 1 && queued) {
      toast(
        failures.length
          ? `Queued ${queued} of ${files.length} books; ${failures.length} failed.`
          : `Queued ${queued} books for import.`,
        { tone: failures.length ? "warn" : "ok" },
      );
    } else if (failures.length) {
      toast(failures[0].error.message || "Upload failed.", { tone: "danger" });
    }
    setBusy(false); setProgress(0); setCurrent(null);
  }

  const pct = Math.round(progress * 100);
  const measured = busy && progress > 0 && progress < 1;
  const level = busy ? (measured ? 0.12 + progress * 0.76 : 0.36) : drag ? 0.52 : near ? 0.2 : 0.075;
  const cls = ["imp-basin", drag ? "is-drag" : "", near && !drag ? "is-near" : "", busy ? "is-busy" : "",
    busy && !measured ? "is-swelling" : ""].filter(Boolean).join(" ");

  return (
    <div className="imp-basin-wrap">
      <div className={cls} role="button" tabIndex={busy ? -1 : 0}
           aria-label="Choose EPUB or PDF books" aria-disabled={busy}
           style={{ "--level": level }}
           onKeyDown={e => {
             if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) {
               e.preventDefault();
               if (!busy) inputRef.current?.click();
             }
           }}
           onClick={() => !busy && inputRef.current && inputRef.current.click()}
           onDragOver={e => { e.preventDefault(); if (!drag) setDrag(true); }}
           onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setDrag(false); }}
           onDrop={e => { e.preventDefault(); setDrag(false); setNear(false); send(e.dataTransfer.files); }}>
        <svg className="imp-basin-rim" aria-hidden="true" focusable="false">
          <rect className="imp-rim-dash" x="1" y="1" width="100%" height="100%" rx="29" />
          <rect className="imp-rim-glow" x="1" y="1" width="100%" height="100%" rx="29" />
        </svg>
        <div className="imp-basin-water" aria-hidden="true">
          <div className="imp-basin-tide">
            <div className="imp-basin-swell">
              <svg className="imp-wave imp-wave-back" viewBox="0 0 400 24" preserveAspectRatio="none">
                <path d="M0 12Q50 3 100 12T200 12T300 12T400 12V24H0Z" />
              </svg>
              <svg className="imp-wave imp-wave-front" viewBox="0 0 400 24" preserveAspectRatio="none">
                <path d="M0 12Q50 21 100 12T200 12T300 12T400 12V24H0Z" />
                <path className="imp-wave-crest" d="M0 12Q50 21 100 12T200 12T300 12T400 12" />
              </svg>
              <div className="imp-basin-depth"><i className="imp-caustic" /><i className="imp-caustic imp-caustic-b" /></div>
            </div>
          </div>
        </div>
        <div className="imp-basin-float">
          <div className="imp-basin-rings" aria-hidden="true"><i /><i /><i /></div>
          <BookGlyph />
        </div>
        <div className="imp-basin-copy">
          <b className="imp-basin-title">{busy
            ? (measured ? `Uploading… ${pct}%` : "Uploading…")
            : drag ? "Release to add your books" : "Drop your books here, or choose files"}</b>
          <span className="imp-basin-sub">
            {busy && current
              ? `${current.total > 1 ? `Book ${current.index + 1} of ${current.total} · ` : ""}${current.name}`
              : "Upload several volumes together, review them, then commit or append them as one series."}
          </span>
        </div>
        <div className="imp-basin-formats">
          <Chip className="mono">.epub</Chip><Chip className="mono">.pdf</Chip>
        </div>
        <input ref={inputRef} type="file" accept=".epub,.pdf" multiple style={{ display: "none" }}
               onChange={e => { send(e.target.files); e.target.value = ""; }} />
      </div>
      {busy && progress > 0 && (
        <ProgressBar live size="sm" value={progress * 100} label="Upload progress" className="imp-basin-progress" />
      )}
    </div>
  );
}
