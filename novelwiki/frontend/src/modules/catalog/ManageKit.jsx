/* ============================================================
   Manage kit — the control room's shared anatomy.
     ManageSection   a ledger row: numbered section title + one-line purpose
                     on the left (sticky on wide screens), its cards right
     ManageCard      card anatomy: icon tile · title · meta, a purpose line,
                     body; catches the pointer's light
     ChoiceCards     radio cards with a sliding selection (real radios)
     Reveal          height-tide disclosure for inline forms
   ============================================================ */
import React, { useId } from "react";
import { Icon } from "../../components/Icon.jsx";
import { AnimatePresence, motion, springs } from "../../motion/index.js";

export function ManageSection({ id, index, title, desc, tone, children }) {
  return (
    <section id={`manage-${id}`} className={"mg-section" + (tone ? ` is-${tone}` : "")} aria-labelledby={`mg-${id}`}>
      <header className="mg-aside">
        <span className="mg-num mono" aria-hidden="true">{String(index).padStart(2, "0")}</span>
        <h2 id={`mg-${id}`} className="mg-title">{title}</h2>
        {desc && <p className="mg-desc">{desc}</p>}
      </header>
      <div className="mg-cards">{children}</div>
    </section>
  );
}

export function ManageCard({ icon, title, sub, meta, tone, as: Tag = "section", className = "", children, ...rest }) {
  const id = useId();
  return (
    <Tag className={["card", "manage-card", tone ? `is-${tone}` : "", className].filter(Boolean).join(" ")}
         aria-labelledby={`${id}-t`} data-spotlight="" {...rest}>
      <div className="mc-head">
        <h3 id={`${id}-t`}>{icon && <Icon name={icon} size={16} />}{title}</h3>
        {meta != null && meta !== false && <div className="mc-meta">{meta}</div>}
      </div>
      {sub && <p className="mc-sub">{sub}</p>}
      {children}
    </Tag>
  );
}

/* A pipeline step inside a card: numbered node on a vertical rail. */
export function Step({ n, title, desc, children, last }) {
  return (
    <div className={"mc-step" + (last ? " is-last" : "")}>
      <span className="mc-step-node mono" aria-hidden="true">{n}</span>
      <div className="mc-step-body">
        <p className="mc-step-title">{title}</p>
        {desc && <p className="mc-step-desc">{desc}</p>}
        {children}
      </div>
    </div>
  );
}

export function ChoiceCards({ legend, value, options, onChange, busy, note }) {
  const name = useId();
  return (
    <fieldset className={"choice" + (busy ? " is-busy" : "")} aria-busy={busy || undefined}>
      <legend className="choice-legend">{legend}</legend>
      <div className="choice-options">
        {options.map(o => {
          const on = o.value === value;
          return (
            <label key={o.value} className={"choice-opt" + (on ? " on" : "")}>
              <input type="radio" name={name} value={o.value} checked={on}
                     onChange={() => { if (!busy && !on) onChange(o.value); }} />
              {on && <motion.span layoutId={`choice-${name}`} className="choice-thumb" transition={springs.layout} aria-hidden="true" />}
              {o.icon && <span className="choice-icon" aria-hidden="true"><Icon name={o.icon} size={16} /></span>}
              <span className="choice-text">
                <span className="choice-label">{o.label}</span>
                {o.desc && <span className="choice-desc">{o.desc}</span>}
              </span>
              <span className="choice-radio" aria-hidden="true" />
            </label>
          );
        })}
      </div>
      {note && <p className="choice-note">{note}</p>}
    </fieldset>
  );
}

const revealMotion = {
  initial: { height: 0, opacity: 0 },
  animate: { height: "auto", opacity: 1, transition: { height: springs.smooth, opacity: { duration: 0.28, delay: 0.06 } } },
  exit: { height: 0, opacity: 0, transition: { height: { duration: 0.26, ease: [0.55, 0, 1, 0.45] }, opacity: { duration: 0.14 } } },
};

export function Reveal({ show, children, className = "" }) {
  return (
    <AnimatePresence initial={false}>
      {show && (
        <motion.div key="reveal" className={["mc-reveal", className].filter(Boolean).join(" ")} {...revealMotion}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
