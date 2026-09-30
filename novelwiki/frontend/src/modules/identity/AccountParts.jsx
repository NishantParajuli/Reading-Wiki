/* ============================================================
   Settings building blocks shared by every Account section:
   SectionHead (medallion + title), Group (a composed glass card),
   Switch (an on/off setting), Slider (range with a live readout) and
   useRadioGroup (roving-tabindex radio semantics for custom pickers).
   ============================================================ */
import React, { useRef } from "react";

import { Icon } from "../../components/Icon.jsx";

export function SectionHead({ id, icon, title, lead }) {
  return (
    <header className="acct-sec-head rise">
      <span className="acct-medallion" aria-hidden="true"><Icon name={icon} size={21} /></span>
      <div className="grow">
        <h2 id={id} className="acct-sec-title">{title}</h2>
        {lead && <p className="acct-sec-lead">{lead}</p>}
      </div>
    </header>
  );
}

/* One composed card inside a section. `as="form"` makes the card the form. */
export function Group({ as: Tag = "div", title, hint, aside, i = 1, className = "", children, ...rest }) {
  return (
    <Tag className={["card acct-card acct-group rise", className].filter(Boolean).join(" ")}
         style={{ "--i": i }} data-spotlight="" {...rest}>
      {(title || aside) && (
        <div className="acct-group-head">
          <div className="grow">
            {title && <h3 className="acct-group-title">{title}</h3>}
            {hint && <p className="acct-group-hint">{hint}</p>}
          </div>
          {aside}
        </div>
      )}
      {children}
    </Tag>
  );
}

/* A labelled on/off control. The native checkbox keeps keyboard + form
   semantics; role="switch" tells assistive tech it applies immediately. */
export function Switch({ checked, onChange, disabled, children, hint }) {
  return (
    <label className={"acct-switch" + (disabled ? " is-disabled" : "")}>
      <input type="checkbox" role="switch" checked={!!checked} disabled={disabled}
             onChange={(e) => onChange(e.target.checked)} />
      <span className="acct-switch-track" aria-hidden="true"><span className="acct-switch-thumb" /></span>
      <span className="acct-switch-text">
        {children}
        {hint && <small>{hint}</small>}
      </span>
    </label>
  );
}

/* Range input with the filled track wired up and a readout beside the label. */
export function Slider({ id, label, value, min, max, step, onChange, display, valueText, minGlyph, maxGlyph }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className="acct-slider">
      <div className="acct-slider-top">
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id} className="acct-slider-val">{display}</output>
      </div>
      <div className="acct-slider-row">
        {minGlyph && <span className="acct-slider-glyph" aria-hidden="true">{minGlyph}</span>}
        <input id={id} type="range" className="slider" min={min} max={max} step={step} value={value}
               aria-valuetext={valueText} style={{ "--fill": `${pct}%` }}
               onChange={(e) => onChange(Number(e.target.value))} />
        {maxGlyph && <span className="acct-slider-glyph lg" aria-hidden="true">{maxGlyph}</span>}
      </div>
    </div>
  );
}

/* Roving tabindex for custom radio groups: one tab stop, arrows move and
   select (WAI-ARIA radio pattern). `onSelect(value, element)` runs on arrow
   selection; clicks are handled by the caller. */
export function useRadioGroup(values, value, onSelect) {
  const refs = useRef(new Map());
  const current = values.indexOf(value);
  const tabStop = current < 0 ? 0 : current;
  const move = (event, index) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    let next = null;
    if (step) next = (index + step + values.length) % values.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = values.length - 1;
    if (next == null) return;
    event.preventDefault();
    const el = refs.current.get(values[next]);
    if (el) el.focus();
    onSelect(values[next], el);
  };
  return (v, index) => ({
    role: "radio",
    "aria-checked": v === value,
    tabIndex: index === tabStop ? 0 : -1,
    ref: (el) => { if (el) refs.current.set(v, el); else refs.current.delete(v); },
    onKeyDown: (event) => move(event, index),
  });
}

/* Centre of an element — the origin for ripples when a pick comes from the keyboard. */
export function centerOf(el) {
  if (!el) return undefined;
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
