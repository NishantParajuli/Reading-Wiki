/* ============================================================
   UI primitives — Button, IconButton, Chip, ProgressBar, Spinner,
   Skeleton, EmptyState, PageHeader, StatTile, RelativeTime,
   SegmentedControl, Cover, avatars, Reveal, Tabs.
   Motion lives in CSS where it can (ripples, sheens, reveals) and in
   motion/react where layout must be animated (sliding tab lozenges).
   ============================================================ */
import React, { useId, useRef, useState } from "react";
import { Icon } from "./Icon.jsx";
import { GeneratedCover } from "./GeneratedCover.jsx";
import { TextReveal } from "../motion/TextReveal.jsx";
import { NumberTicker } from "../motion/NumberTicker.jsx";
import { motion, springs } from "../motion/index.js";
import { TYPE_ICON, TYPE_LABEL } from "../lib/constants.js";
import { relativeTime } from "../lib/utils.js";

/* A loading button stays focusable (aria-disabled, not disabled): a natively
   disabled button drops keyboard focus to <body> mid-save. Its clicks (and
   Enter's implicit form submission) are cancelled until the work finishes. */
export function Button({ variant = "primary", size, icon, iconRight, loading, full, className = "", children, disabled, type = "button", onClick, ...rest }) {
  const cls = ["btn", `btn-${variant}`, size ? size : "", full ? "full" : "", loading ? "is-loading" : "", className].filter(Boolean).join(" ");
  const busy = !!loading && !disabled;
  return (
    <button type={type} className={cls} disabled={disabled} aria-disabled={busy || undefined} aria-busy={loading || undefined}
            onClick={busy ? (e) => e.preventDefault() : onClick} {...rest}>
      {loading ? <span className="btn-spinner" aria-hidden /> : (icon ? <Icon name={icon} size={size === "sm" ? 14 : size === "lg" ? 18 : 16} /> : null)}
      {children}
      {iconRight && <Icon name={iconRight} size={size === "sm" ? 14 : size === "lg" ? 18 : 16} />}
    </button>
  );
}

export function IconButton({ label, name, size = 17, active, badge, plain, className = "", ...rest }) {
  const cls = ["icon-btn", active ? "active" : "", plain ? "plain" : "", className].filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} aria-label={label} title={label} {...rest}>
      <Icon name={name} size={size} />
      {badge != null && badge !== 0 && <span className="ib-badge">{badge}</span>}
    </button>
  );
}

export function Chip({ tone = "neutral", icon, className = "", children, ...rest }) {
  const toneCls = tone !== "neutral" ? `chip-${tone}` : "";
  return (
    <span className={["chip", toneCls, className].filter(Boolean).join(" ")} {...rest}>
      {icon && <Icon name={icon} size={12} sw={2} />}
      {children}
    </span>
  );
}

export function ProgressBar({ value = 0, size = "md", tone, label, live, className = "", style }) {
  const pct = Number.isFinite(Number(value)) ? Math.max(0, Math.min(100, Number(value))) : 0;
  return (
    <div className={["progress-track", size !== "md" ? size : "", live ? "live" : "", className].filter(Boolean).join(" ")}
         role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}
         aria-label={label || "Progress"} style={style}>
      <div className={["progress-fill", tone || ""].filter(Boolean).join(" ")} style={{ width: `${pct}%` }} />
    </div>
  );
}

/* Circular progress (reading position, completion). */
export function ProgressRing({ value = 0, size = 44, stroke = 3, label, children, className = "" }) {
  const pct = Number.isFinite(Number(value)) ? Math.max(0, Math.min(100, Number(value))) : 0;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  return (
    <span className={["progress-ring", className].filter(Boolean).join(" ")} style={{ width: size, height: size }}
          role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label || "Progress"}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="pr-track" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="pr-fill"
                strokeDasharray={circumference} strokeDashoffset={circumference * (1 - pct / 100)}
                transform={`rotate(-90 ${size / 2} ${size / 2})`} strokeLinecap="round" />
      </svg>
      {children != null && <span className="pr-label">{children}</span>}
    </span>
  );
}

export function Spinner({ size }) {
  return <div className={"spinner" + (size === "lg" ? " lg" : "")} aria-hidden />;
}

export function Loading({ label = "Loading…" }) {
  return (
    <div className="loading-row" role="status">
      <span className="loading-dots" aria-hidden="true">
        <i style={{ "--d": 0 }} /><i style={{ "--d": 1 }} /><i style={{ "--d": 2 }} />
      </span>
      {label}
    </div>
  );
}

export function Skeleton({ variant = "rect", width, height, className = "", style }) {
  return <div className={["skeleton", variant, className].filter(Boolean).join(" ")} style={{ width, height, ...style }} aria-hidden />;
}

export function EmptyState({ icon = "search", title, body, primaryAction, secondaryAction }) {
  return (
    <div className="empty-state rise">
      <div className="es-icon"><Icon name={icon} size={26} /></div>
      <b>{title}</b>
      {body && <p>{body}</p>}
      {(primaryAction || secondaryAction) && (
        <div className="es-actions">
          {primaryAction}
          {secondaryAction}
        </div>
      )}
    </div>
  );
}

export function PageHeader({ title, subtitle, eyebrow, actions, children }) {
  return (
    <div className="page-head">
      <div className="grow">
        {eyebrow && <p className="section-eyebrow rise">{eyebrow}</p>}
        <TextReveal as="h1" className="page-title" text={typeof title === "string" ? title : undefined}>{title}</TextReveal>
        {subtitle && <p className="page-sub rise" style={{ "--i": 3 }}>{subtitle}</p>}
        {children}
      </div>
      {actions && <div className="page-head-actions rise" style={{ "--i": 4 }}>{actions}</div>}
    </div>
  );
}

export function StatTile({ value, label, tone }) {
  return (
    <div className="stat-tile">
      <div className={"st-num" + (tone ? " " + tone : "")}>
        {typeof value === "number" ? <NumberTicker value={value} /> : value}
      </div>
      <div className="st-label">{label}</div>
    </div>
  );
}

export function RelativeTime({ iso, prefix = "" }) {
  if (!iso) return null;
  const abs = new Date(iso).toLocaleString();
  return <time dateTime={iso} title={abs}>{prefix}{relativeTime(iso)}</time>;
}

export function SegmentedControl({ value, onChange, options, fit, className = "", ariaLabel }) {
  const group = useId();
  return (
    <div className={["seg", fit ? "fit" : "", className].filter(Boolean).join(" ")} role="group" aria-label={ariaLabel}>
      {options.map(o => {
        const on = value === o.value;
        return (
          <button key={String(o.value)} type="button"
                  className={on ? "active" : ""}
                  aria-pressed={on}
                  title={o.title}
                  aria-label={o.title || (typeof o.label === "string" ? o.label : undefined)}
                  onClick={() => onChange(o.value)}>
            {on && <motion.span layoutId={`seg-${group}`} className="seg-thumb" transition={springs.layout} aria-hidden="true" />}
            {o.icon && <Icon name={o.icon} size={14} sw={2} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* Book jacket: fixed 2:3, lazy image, generated art when the image is missing
   or broken. `tilt` enables pointer tilt + glare; `vtName` names it for view
   transitions (the novel hero uses "hero-cover"). Every cover is tagged so a
   clicked card's jacket can fly into the hero. */
export function Cover({ src, title, author, tilt = false, vtName, className = "", style }) {
  const [failedSrc, setFailedSrc] = useState(null);
  const showImage = src && failedSrc !== src;
  return (
    <div className={["cover", className].filter(Boolean).join(" ")}
         style={vtName ? { ...style, viewTransitionName: vtName } : style}
         data-vt-cover=""
         data-vt-hero={vtName ? "" : undefined}
         data-tilt={tilt ? (typeof tilt === "number" ? tilt : 9) : undefined}>
      {showImage
        ? <img src={src} alt="" loading="lazy" decoding="async" onError={() => setFailedSrc(src)} />
        : <GeneratedCover title={title} author={author} />}
    </div>
  );
}

export function UserAvatar({ url, name, size = 32, className = "", ...rest }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  const style = { width: size, height: size, fontSize: Math.round(size * 0.44) };
  if (url) return <img className={["avatar-user", className].join(" ")} src={url} alt="" style={style} {...rest} />;
  return <div className={["avatar-user", className].join(" ")} style={style} {...rest}>{initial}</div>;
}

/* Entity orb (codex): a monogram in a type-tinted glass sphere. */
export function EntityAvatar({ entity, lg, locked }) {
  const name = (entity && (entity.name || entity.canonical_name)) || "";
  const letter = locked ? "" : (name.trim().charAt(0).toUpperCase() || "");
  return (
    <div className={`avatar ${lg ? "lg" : ""} t-${entity.type} ${locked ? "is-locked" : ""}`} aria-hidden="true">
      {letter ? <span className="orb-letter">{letter}</span> : <Icon name={locked ? "lock" : (TYPE_ICON[entity.type] || "spark")} size={lg ? 34 : 20} />}
      {letter && <Icon name={TYPE_ICON[entity.type] || "spark"} size={lg ? 16 : 11} sw={2} className="orb-icon" />}
    </div>
  );
}

export function TypeBadge({ type }) {
  return (
    <span className={`badge t-${type}`}>
      <Icon name={TYPE_ICON[type] || "spark"} size={12} sw={2} />
      {TYPE_LABEL[type] || type}
    </span>
  );
}

/* Reveal wrapper: shows children when ceiling >= chapter, else a redacted cover. */
export function Reveal({ chapter, ceiling, lines = 2, label, children, className = "" }) {
  const locked = ceiling < chapter;
  const lockLabel = label || `Unlocks at ch. ${chapter}`;
  return (
    <div className={`reveal ${locked ? "locked" : ""} ${className}`}>
      <div className="r-content" aria-hidden={locked} inert={locked ? "" : undefined}>{children}</div>
      <div className="r-cover">
        <div className="redact">
          {Array.from({ length: lines }).map((_, i) => (
            <span key={i} style={{ width: i === lines - 1 ? "62%" : "100%" }} />
          ))}
        </div>
        <span className="lock-pill"><Icon name="lock" size={12} className="lk" /> {lockLabel}</span>
      </div>
    </div>
  );
}

/* Pill tabs (Library shelves, Jobs Active/History, Admin) with a sliding lozenge. */
/* ARIA tabs with automatic activation: one Tab stop (the selected tab), arrows
   and Home/End move and select. `label` names the tablist. With `idBase`, tab
   ids are `${idBase}-tab-<id>` and every tab controls `${idBase}-panel`, so the
   caller can render <div role="tabpanel" id={`${idBase}-panel`}
   aria-labelledby={`${idBase}-tab-${value}`}>. */
export function Tabs({ tabs, value, onChange, className = "", label, idBase }) {
  const group = useId();
  const refs = useRef({});
  const current = Math.max(0, tabs.findIndex(t => t.id === value));
  const select = (index) => {
    const next = tabs[(index + tabs.length) % tabs.length];
    if (!next) return;
    onChange(next.id);
    const el = refs.current[next.id];
    if (el) el.focus();
  };
  const onKeyDown = (e) => {
    const to = { ArrowRight: current + 1, ArrowLeft: current - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (to == null) return;
    e.preventDefault();
    select(to);
  };
  return (
    <div className={["tabs", className].filter(Boolean).join(" ")} role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map(t => {
        const on = value === t.id;
        return (
          <button key={t.id} type="button" role="tab" aria-selected={on} tabIndex={on ? 0 : -1}
                  ref={el => { refs.current[t.id] = el; }}
                  id={idBase ? `${idBase}-tab-${t.id}` : undefined}
                  aria-controls={idBase ? `${idBase}-panel` : undefined}
                  className={"tab" + (on ? " active" : "")}
                  onClick={() => onChange(t.id)}>
            {on && <motion.span layoutId={`tabs-${group}`} className="tab-lozenge" transition={springs.layout} aria-hidden="true" />}
            {t.icon && <Icon name={t.icon} size={14} />}
            {t.label}
            {t.count != null && <span className="tab-count">{t.count}</span>}
            {t.dot && <span className="tab-dot" aria-label="attention" />}
          </button>
        );
      })}
    </div>
  );
}
