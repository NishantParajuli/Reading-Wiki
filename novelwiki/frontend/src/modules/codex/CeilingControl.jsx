/* Compact ceiling control (§6.8) — replaces the sticky CeilingBar. A pill in
   the codex header ("Bounded to Ch. 512 ▾") opening a popover with the
   slider, revealed count, and a follow-my-reading reset. Same clamping. */
import React, { useState } from "react";
import { Icon } from "../../components/Icon.jsx";
import { Button } from "../../components/ui.jsx";
import { Popover } from "../../components/overlay.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { fmtChapter } from "../../lib/utils.js";

export function CeilingControl() {
  const { ceiling, setCeiling, stats, codexMeta } = useNovel();
  const [open, setOpen] = useState(false);

  const min = (codexMeta && codexMeta.min) || 1;
  const max = Math.max((codexMeta && codexMeta.max) || min, min);
  const bookMax = (codexMeta && codexMeta.bookMax) || max;
  const lockedAhead = bookMax > max;
  const title = stats && stats.ceiling_title;
  const revealed = stats == null ? "—" : stats.entities_revealed;

  return (
    <Popover open={open} onClose={() => setOpen(false)} className="ceiling-panel" trigger={
      <button className="ceiling-pill" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Icon name="book" size={14} />
        Bounded to <b>Ch. {fmtChapter(ceiling)}</b>
        <Icon name="chevronDown" size={13} />
      </button>
    }>
      <div className="col" style={{ gap: 12 }}>
        <div>
          <div className="section-eyebrow" style={{ marginBottom: 4 }}>Codex bounded to</div>
          <b className="serif" style={{ fontSize: "var(--text-lg)" }}>
            {title ? `Ch. ${fmtChapter(ceiling)} · ${title}` : `Chapter ${fmtChapter(ceiling)}`}
          </b>
        </div>
        <div className="row" style={{ gap: 12 }}>
          <input type="range" className="slider" min={min} max={max} value={Math.min(ceiling, max)}
                 step={1} disabled={max <= min}
                 onChange={e => setCeiling(+e.target.value)}
                 aria-label="Chapter ceiling" style={{ flex: 1 }} />
          <span className="chip mono">{fmtChapter(ceiling)}/{fmtChapter(max)}</span>
        </div>
        <div className="ceiling-stat">
          {lockedAhead
            ? <><Icon name="lock" size={12} /> read further to unlock later chapters</>
            : <><b>{revealed}</b> entities revealed</>}
        </div>
        <Button variant="ghost" size="sm" icon="refresh" onClick={() => { setCeiling(max); setOpen(false); }}>
          Follow my reading (Ch. {fmtChapter(max)})
        </Button>
      </div>
    </Popover>
  );
}
