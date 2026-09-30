/* ============================================================
   Admin console pieces: metric tiles (count-up figures), compact quota
   meters, worker status orbs, the section block header, and the
   visibility pill select used by moderation.
   ============================================================ */
import React from "react";

import { Icon } from "../../components/Icon.jsx";
import { NumberTicker } from "../../motion/NumberTicker.jsx";

export function MetricTile({ icon, value, label, tone, i = 0, note }) {
  return (
    <div className={"adm-metric rise" + (tone ? ` tone-${tone}` : "")} style={{ "--i": i }} data-spotlight="">
      <span className="adm-metric-ico" aria-hidden="true"><Icon name={icon} size={16} /></span>
      <span className="adm-metric-num">{typeof value === "number" ? <NumberTicker value={value} /> : value}</span>
      <span className="adm-metric-label">{label}</span>
      {note && <span className="adm-metric-note">{note}</span>}
    </div>
  );
}

export function severity(pct) {
  return pct >= 100 ? "danger" : pct >= 80 ? "warn" : "";
}

/* A hairline quota meter: the fill carries severity over a same-hue track. */
export function MiniMeter({ label, used, limit, owner }) {
  const u = Number(used) || 0;
  const l = Number(limit) || 0;
  const pct = l > 0 ? Math.min(100, (u / l) * 100) : 0;
  const tone = severity(pct);
  return (
    <div className={"adm-meter" + (tone ? ` is-${tone}` : "")}>
      <div className="adm-meter-top">
        <span className="adm-meter-label">{label}</span>
        <span className="adm-meter-fig">{u.toLocaleString()}<i>/{l.toLocaleString()}</i></span>
      </div>
      <div className="adm-meter-track" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}
           aria-label={`${owner ? `${owner} — ` : ""}${label}: ${u} of ${l}`}>
        <span style={{ transform: `scaleX(${pct / 100})` }} />
      </div>
    </div>
  );
}

/* A glass sphere whose light is the worker's state; it pulses while busy. */
export function StatusOrb({ tone, busy, label }) {
  return (
    <span className={`adm-orb tone-${tone}` + (busy ? " is-busy" : "")} role="img" aria-label={label}>
      {busy && <><span className="adm-orb-pulse" /><span className="adm-orb-pulse late" /></>}
      <span className="adm-orb-core" />
    </span>
  );
}

export function BlockHead({ id, eyebrow, title, aside }) {
  return (
    <header className="adm-block-head">
      <div className="grow">
        {eyebrow && <p className="section-eyebrow">{eyebrow}</p>}
        <h2 id={id} className="adm-block-title">{title}</h2>
      </div>
      {aside}
    </header>
  );
}

export const VISIBILITY = {
  private: { label: "Private", icon: "lock", hint: "Only the owner" },
  public: { label: "Public", icon: "eye", hint: "Anyone can find and read" },
  global: { label: "Global", icon: "globe", hint: "In the shared library" },
};

export function VisibilitySelect({ value, onChange, title, disabled }) {
  const v = VISIBILITY[value] || VISIBILITY.private;
  return (
    <span className={`adm-vis vis-${value}`}>
      <Icon name={v.icon} size={14} />
      <select value={value} onChange={e => onChange(e.target.value)} disabled={disabled}
              title="Visibility" aria-label={`Visibility of ${title}`}>
        {Object.keys(VISIBILITY).map(k => <option key={k} value={k}>{VISIBILITY[k].label}</option>)}
      </select>
      <Icon name="chevronDown" size={13} className="adm-vis-chev" />
    </span>
  );
}

export const fmtDay = (s) => (s ? new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "never");
