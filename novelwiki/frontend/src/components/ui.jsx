/* ============================================================
   UI primitives — Button, IconButton, Chip, ProgressBar, Spinner,
   Skeleton, EmptyState, PageHeader, StatTile, RelativeTime,
   SegmentedControl, Cover, avatars, Reveal, Tabs.
   ============================================================ */
import React from "react";
import { Icon } from "./Icon.jsx";
import { TYPE_ICON, TYPE_LABEL } from "../lib/constants.js";
import { coverHues, relativeTime } from "../lib/utils.js";

export function Button({ variant = "primary", size, icon, iconRight, loading, full, className = "", children, disabled, type = "button", ...rest }) {
  const cls = ["btn", `btn-${variant}`, size ? size : "", full ? "full" : "", className].filter(Boolean).join(" ");
  return (
    <button type={type} className={cls} disabled={disabled || loading} {...rest}>
      {loading ? <span className="btn-spinner" aria-hidden /> : (icon ? <Icon name={icon} size={size === "sm" ? 14 : 16} /> : null)}
      {children}
      {iconRight && <Icon name={iconRight} size={size === "sm" ? 14 : 16} />}
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

export function ProgressBar({ value = 0, size = "md", tone, label, className = "", style }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={["progress-track", size !== "md" ? size : "", className].filter(Boolean).join(" ")}
         role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}
         aria-label={label} style={style}>
      <div className={["progress-fill", tone || ""].filter(Boolean).join(" ")} style={{ width: pct + "%" }} />
    </div>
  );
}

export function Spinner({ size }) {
  return <div className={"spinner" + (size === "lg" ? " lg" : "")} aria-hidden />;
}

export function Loading({ label = "Loading…" }) {
  return <div className="loading-row"><Spinner /> {label}</div>;
}

export function Skeleton({ variant = "rect", width, height, className = "", style }) {
  return <div className={["skeleton", variant, className].filter(Boolean).join(" ")} style={{ width, height, ...style }} aria-hidden />;
}

export function EmptyState({ icon = "search", title, body, primaryAction, secondaryAction }) {
  return (
    <div className="empty-state">
      <div className="es-icon"><Icon name={icon} size={22} /></div>
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

export function PageHeader({ title, subtitle, actions, children }) {
  return (
    <div className="page-head">
      <div className="grow">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-sub">{subtitle}</p>}
        {children}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </div>
  );
}

export function StatTile({ value, label, tone }) {
  return (
    <div className="stat-tile">
      <div className={"st-num" + (tone ? " " + tone : "")}>{value}</div>
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
  return (
    <div className={["seg", fit ? "fit" : "", className].filter(Boolean).join(" ")} role="group" aria-label={ariaLabel}>
      {options.map(o => (
        <button key={String(o.value)} type="button"
                className={value === o.value ? "active" : ""}
                aria-pressed={value === o.value}
                title={o.title}
                onClick={() => onChange(o.value)}>
          {o.icon && <Icon name={o.icon} size={14} sw={2} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* Cover with fixed 2:3 ratio, lazy loading, and a deterministic per-title
   gradient placeholder with the title typeset in serif. */
export function Cover({ src, title, className = "", style }) {
  const [h1, h2] = coverHues(title);
  return (
    <div className={["cover", className].filter(Boolean).join(" ")} style={style}>
      {src
        ? <img src={src} alt="" loading="lazy" decoding="async" />
        : <div className="cover-ph" style={{ "--cov-h1": h1, "--cov-h2": h2 }}><span>{title || ""}</span></div>}
    </div>
  );
}

export function UserAvatar({ url, name, size = 32, className = "", ...rest }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  const style = { width: size, height: size, fontSize: Math.round(size * 0.42) };
  if (url) return <img className={["avatar-user", className].join(" ")} src={url} alt="" style={style} {...rest} />;
  return <div className={["avatar-user", className].join(" ")} style={style} {...rest}>{initial}</div>;
}

/* Entity avatar (codex): type-tinted striped placeholder. */
export function EntityAvatar({ entity, lg, locked }) {
  return (
    <div className={`avatar ${lg ? "lg" : ""} t-${entity.type}`}>
      <div className="ph"><div className="ph-label">{locked ? "—" : entity.portrait}</div></div>
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
      <div className="r-content" aria-hidden={locked}>{children}</div>
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

/* Pill tabs (Library shelves, Jobs Active/History, Admin). */
export function Tabs({ tabs, value, onChange, className = "" }) {
  return (
    <div className={["tabs", className].filter(Boolean).join(" ")} role="tablist">
      {tabs.map(t => (
        <button key={t.id} type="button" role="tab" aria-selected={value === t.id}
                className={"tab" + (value === t.id ? " active" : "")}
                onClick={() => onChange(t.id)}>
          {t.icon && <Icon name={t.icon} size={14} />}
          {t.label}
          {t.count != null && <span className="tab-count">{t.count}</span>}
          {t.dot && <span className="tab-dot" aria-label="attention" />}
        </button>
      ))}
    </div>
  );
}
