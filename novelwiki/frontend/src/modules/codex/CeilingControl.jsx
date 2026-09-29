/* Tide gauge (§6.8) — the Codex's chapter boundary. A glass pill (a small
   orb whose water level is how deep into the book you are) opens a gauge:
   exact chapter entry, a tide-staff slider for coarse browsing, the revealed
   count, and a follow-my-reading reset. The server still applies the
   trusted-progress clamp; the local bounds make mistakes clear before a
   request is made. The slider can only look backwards — never past what the
   reader has actually read. */
import React, { useEffect, useId, useMemo, useState } from "react";
import { Icon } from "../../components/Icon.jsx";
import { Button } from "../../components/ui.jsx";
import { Popover } from "../../components/overlay.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { AnimatePresence, motion } from "../../motion/index.js";
import { fmtChapter } from "../../lib/utils.js";
import { fraction, gaugeTicks } from "./presentation.js";
import { TideGlyph, Ticker } from "./parts.jsx";

const numeralMotion = {
  initial: { y: "0.45em", opacity: 0, filter: "blur(6px)" },
  animate: { y: 0, opacity: 1, filter: "blur(0px)" },
  exit: { y: "-0.45em", opacity: 0, filter: "blur(6px)" },
  transition: { type: "spring", stiffness: 520, damping: 38, mass: 0.7 },
};

export function CeilingControl() {
  const { ceiling, setCeiling, stats, codexMeta } = useNovel();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [chapterInput, setChapterInput] = useState(() => fmtChapter(ceiling));
  const [chapterError, setChapterError] = useState("");

  const min = (codexMeta && codexMeta.min) || 1;
  const max = Math.max((codexMeta && codexMeta.max) || min, min);
  const bookMax = (codexMeta && codexMeta.bookMax) || max;
  const lockedAhead = bookMax > max;
  // Stats trail the ceiling by a debounce + request; never show figures that
  // belong to a different boundary than the one on screen.
  const statsCurrent = stats != null && (stats.effective_ceiling == null || Number(stats.effective_ceiling) === Number(ceiling));
  const title = statsCurrent ? stats.ceiling_title : null;
  const revealed = statsCurrent && stats.entities_revealed != null ? Number(stats.entities_revealed) : null;
  const level = fraction(ceiling, min, bookMax);
  const fill = fraction(Math.min(ceiling, max), min, max);
  const ticks = useMemo(() => gaugeTicks(min, max), [min, max]);

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

  const following = Number(ceiling) === Number(max);

  return (
    <Popover open={open} onClose={() => setOpen(false)} className="cx-gauge-panel" trigger={
      <button type="button" className={"cx-gauge-pill" + (open ? " is-open" : "")}
              aria-expanded={open} aria-controls={open ? panelId : undefined}
              onClick={() => setOpen(o => !o)}>
        <TideGlyph level={level} />
        <span className="cx-gauge-pill-label">Bounded to</span>
        <b className="cx-gauge-pill-ch">Ch. {fmtChapter(ceiling)}</b>
        <Icon name="chevronDown" size={13} sw={2} className="cx-gauge-pill-chev" />
      </button>
    }>
      <div className="cx-gauge" id={panelId}>
        <div className="cx-gauge-head">
          <div className="cx-gauge-reading">
            <div className="section-eyebrow">Codex bounded to</div>
            <div className="cx-gauge-numeral" aria-hidden="true">
              <span className="cx-gauge-ch">Ch.</span>
              <span className="cx-gauge-num">
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.span key={String(ceiling)} className="cx-gauge-digits" {...numeralMotion}>
                    {fmtChapter(ceiling)}
                  </motion.span>
                </AnimatePresence>
              </span>
            </div>
            <p className="cx-gauge-title">
              <span className="sr-only">Chapter {fmtChapter(ceiling)}</span>
              {title ? <em>{title}</em> : <span aria-hidden="true">{following ? "Following your reading" : "Looking back"}</span>}
            </p>
          </div>
          <TideGlyph level={level} size={62} className="cx-gauge-orb" />
        </div>

        <form className="ceiling-jump cx-gauge-jump" onSubmit={submitChapter} noValidate>
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
            ? <span id="ceiling-chapter-error" className="ceiling-jump-error" role="alert"><Icon name="circleAlert" size={13} sw={2} /> {chapterError}</span>
            : <span id="ceiling-chapter-help" className="ceiling-jump-help">
                Available: Ch. {fmtChapter(min)}–{fmtChapter(max)}
              </span>}
        </form>

        <div className={"cx-gauge-staff" + (max <= min ? " is-disabled" : "")}>
          <div className="cx-gauge-rule" aria-hidden="true">
            {ticks.map(t => (
              <span key={t.key} className={"cx-tick" + (t.major ? " is-major" : "") + (t.at <= fill + 1e-9 ? " is-lit" : "")}
                    style={{ "--at": t.at }}>
                {t.label != null && <em>{t.label}</em>}
              </span>
            ))}
          </div>
          <input type="range" className="slider cx-gauge-range" min={min} max={max} value={Math.min(ceiling, max)}
                 step={1} disabled={max <= min}
                 style={{ "--fill": fill }}
                 onChange={e => chooseChapter(e.target.value)}
                 aria-label="Browse chapter ceiling" />
          <p className="cx-gauge-hint" aria-hidden="true"><Icon name="wave" size={12} /> Lower the tide to look back</p>
        </div>

        <div className="cx-gauge-stats">
          <div className="cx-gauge-stat">
            <b>{revealed == null ? "—" : <Ticker value={revealed} />}</b>
            <span>entities revealed</span>
          </div>
          {lockedAhead && (
            <div className="cx-gauge-lock">
              <Icon name="lock" size={12} sw={2} /> Read further to unlock later chapters
            </div>
          )}
        </div>

        <Button variant={following ? "ghost" : "secondary"} size="sm" icon="refresh" full onClick={followReading}>
          Follow my reading (Ch. {fmtChapter(max)})
        </Button>
      </div>
    </Popover>
  );
}
