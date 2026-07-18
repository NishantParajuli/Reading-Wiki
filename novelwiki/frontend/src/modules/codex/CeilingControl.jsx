/* Compact ceiling control (§6.8) — a pill in the codex header opening a
   popover with exact chapter entry, a coarse slider, revealed count, and a
   follow-my-reading reset. The server still applies the trusted-progress
   clamp; the local bounds make mistakes clear before a request is made. */
import React, { useEffect, useState } from "react";
import { Icon } from "../../components/Icon.jsx";
import { Button } from "../../components/ui.jsx";
import { Popover } from "../../components/overlay.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { fmtChapter } from "../../lib/utils.js";

export function CeilingControl() {
  const { ceiling, setCeiling, stats, codexMeta } = useNovel();
  const [open, setOpen] = useState(false);
  const [chapterInput, setChapterInput] = useState(() => fmtChapter(ceiling));
  const [chapterError, setChapterError] = useState("");

  const min = (codexMeta && codexMeta.min) || 1;
  const max = Math.max((codexMeta && codexMeta.max) || min, min);
  const bookMax = (codexMeta && codexMeta.bookMax) || max;
  const lockedAhead = bookMax > max;
  const title = stats && stats.ceiling_title;
  const revealed = stats == null ? "—" : stats.entities_revealed;

  useEffect(() => {
    setChapterInput(fmtChapter(ceiling));
    setChapterError("");
  }, [ceiling]);

  function chooseChapter(value) {
    const chapter = Number(value);
    if (!String(value).trim() || !Number.isFinite(chapter)) {
      setChapterError("Enter a chapter number.");
      return;
    }
    if (chapter < min || chapter > max) {
      setChapterError(`Choose a chapter from ${fmtChapter(min)} to ${fmtChapter(max)}.`);
      return;
    }
    setChapterInput(fmtChapter(chapter));
    setChapterError("");
    setCeiling(chapter);
  }

  function submitChapter(e) {
    e.preventDefault();
    chooseChapter(chapterInput);
  }

  function followReading() {
    chooseChapter(max);
    setOpen(false);
  }

  return (
    <Popover open={open} onClose={() => setOpen(false)} className="ceiling-panel" trigger={
      <button className="ceiling-pill" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Icon name="book" size={14} />
        Bounded to <b>Ch. {fmtChapter(ceiling)}</b>
        <Icon name="chevronDown" size={13} />
      </button>
    }>
      <div className="col" style={{ gap: 14 }}>
        <div>
          <div className="section-eyebrow" style={{ marginBottom: 4 }}>Codex bounded to</div>
          <b className="serif" style={{ fontSize: "var(--text-lg)" }}>
            {title ? `Ch. ${fmtChapter(ceiling)} · ${title}` : `Chapter ${fmtChapter(ceiling)}`}
          </b>
        </div>

        <form className="ceiling-jump" onSubmit={submitChapter} noValidate>
          <label htmlFor="ceiling-chapter-input">Go directly to chapter</label>
          <div className="ceiling-jump-row">
            <div className={"ceiling-number-input" + (chapterError ? " has-error" : "")}>
              <span aria-hidden="true">Ch.</span>
              <input id="ceiling-chapter-input" type="number" inputMode="decimal"
                     min={min} max={max} step="any" value={chapterInput}
                     onChange={e => { setChapterInput(e.target.value); setChapterError(""); }}
                     onFocus={e => e.target.select()} aria-invalid={Boolean(chapterError)}
                     aria-describedby={chapterError ? "ceiling-chapter-error" : "ceiling-chapter-help"}
                     enterKeyHint="go" />
            </div>
            <Button type="submit" variant="primary" size="sm">Set</Button>
          </div>
          {chapterError
            ? <span id="ceiling-chapter-error" className="ceiling-jump-error" role="alert">{chapterError}</span>
            : <span id="ceiling-chapter-help" className="ceiling-jump-help">
                Available: Ch. {fmtChapter(min)}–{fmtChapter(max)}
              </span>}
        </form>

        <div className="ceiling-slider">
          <div className="ceiling-slider-labels" aria-hidden="true">
            <span>{fmtChapter(min)}</span><span>Drag to browse</span><span>{fmtChapter(max)}</span>
          </div>
          <input type="range" className="slider" min={min} max={max} value={Math.min(ceiling, max)}
                 step={1} disabled={max <= min}
                 onChange={e => chooseChapter(e.target.value)}
                 aria-label="Browse chapter ceiling" />
        </div>
        <div className="ceiling-stat">
          {lockedAhead
            ? <><Icon name="lock" size={12} /> read further to unlock later chapters</>
            : <><b>{revealed}</b> entities revealed</>}
        </div>
        <Button variant="ghost" size="sm" icon="refresh" onClick={followReading}>
          Follow my reading (Ch. {fmtChapter(max)})
        </Button>
      </div>
    </Popover>
  );
}
