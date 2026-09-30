/* ============================================================
   Discover parts — the shared library as an editorial front page.

   · FeaturedStrip  the first stories under the current sort, set like a
                    magazine cover: a cinematic lead (large tilting jacket,
                    the book's own light behind it, blurb) and two companions.
   · DiscoverCard   a jacket on the shared shelf with feature tags (Codex,
                    Audio, translation, language) and an Add action that
                    turns into "In library".
   · FilterBar      glass pills with popover menus (desktop; real menus, see
                    useMenu.js) and a filter sheet on phones; everything
                    mirrors the URL. Under reduced motion nothing fades in.
   Nothing here invents data: labels, counts and blurbs are the server's own.
   ============================================================ */
import React, { forwardRef, useState } from "react";
import { Link } from "react-router-dom";

import { Icon } from "../../components/Icon.jsx";
import { Button, Cover } from "../../components/ui.jsx";
import { Dialog, MenuItem, Popover } from "../../components/overlay.jsx";
import { ease, motion, springs, useReducedMotion } from "../../motion/index.js";
import {
  GENRE_TAGS, STATUS_TAG_LABELS, STATUS_TAG_RADIO_GROUPS, TRANSLATION_TYPE_LABELS,
} from "../../lib/constants.js";
import { coverHues } from "../../lib/utils.js";
import { bodyVariants, itemMotion, stageVariants } from "./LibraryParts.jsx";
import { menuItemProps, useMenu } from "./useMenu.js";

export const LANGS = [["en", "English"], ["ja", "Japanese"], ["ko", "Korean"], ["zh", "Chinese"]];
export const TRANSLATIONS = [["translated", "Translated"], ["raws", "Raws"], ["raws+translated", "Raws + Translated"]];
export const FRESHNESS = [["fresh_7d", "Scraped in 7 days"], ["fresh_30d", "Scraped in 30 days"], ["stale_30d", "Stale 30+ days"], ["never_scraped", "Never scraped"]];
export const DISCOVER_SORTS = [
  { id: "recent", label: "Recently updated" },
  { id: "fresh", label: "Freshest source" },
  { id: "title", label: "Title (A–Z)" },
];
export const TAG_GROUPS = [
  ...STATUS_TAG_RADIO_GROUPS.map(g => ({ label: g.label, options: g.tags.map(t => [t, STATUS_TAG_LABELS[t] || t]) })),
  { label: "Genre", options: GENRE_TAGS.map(t => [t, STATUS_TAG_LABELS[t] || t]) },
];
const LANG_NAME = Object.fromEntries(LANGS);

/* Per-book light for panels without the room's atmosphere. */
function hueStyle(n) {
  const [h1, h2] = coverHues(n.title);
  return { "--bh1": h1, "--bh2": h2 };
}

function metaLine(n) {
  const count = Number(n.chapter_count) || 0;
  return [
    count ? `${count.toLocaleString()} ${count === 1 ? "chapter" : "chapters"}` : null,
    n.owner_username ? `@${n.owner_username}` : null,
  ].filter(Boolean).join(" · ");
}

/* ---------- add ---------- */
function AddGlyph({ added }) {
  return (
    <svg className={"add-glyph" + (added ? " is-added" : "")} width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path className="ag-plus" d="M12 5v14M5 12h14" />
      <path className="ag-check" d="M5 12.5l4.5 4.5L19 7.5" pathLength="1" />
    </svg>
  );
}

/** Add to library → In library. Stays focusable once added (aria-disabled). */
export function AddButton({ n, added, onAdd, variant = "cover" }) {
  const onClick = (e) => {
    if (added) return;
    const card = e.currentTarget.closest("[data-vt-card]");
    onAdd(n, card ? card.querySelector("[data-vt-cover]") : null);
  };
  const common = {
    type: "button",
    "aria-disabled": added || undefined,
    "aria-label": added ? "In library" : `Add ${n.title} to library`,
    onClick,
  };
  if (variant === "hero") {
    return (
      <button {...common} className={"btn lg disc-add-hero " + (added ? "btn-ghost is-added" : "btn-primary")}>
        <AddGlyph added={added} />
        <span aria-hidden="true">{added ? "In library" : "Add to library"}</span>
      </button>
    );
  }
  return (
    <button {...common} className={`disc-add is-${variant}` + (added ? " is-added" : "")}>
      <AddGlyph added={added} />
      <span aria-hidden="true">{added ? "In library" : "Add"}</span>
    </button>
  );
}

/* ---------- feature tags ---------- */
export function FeatureTags({ n, className = "" }) {
  const lang = n.language || n.original_language;
  const tags = [];
  if (n.has_codex) tags.push(<li key="codex" className="disc-tag is-codex"><Icon name="compass" size={12} sw={2} />Codex</li>);
  if (n.has_audio) tags.push(<li key="audio" className="disc-tag is-audio"><Icon name="headphones" size={12} sw={2} />Audio</li>);
  if (n.translation_type) tags.push(<li key="tr" className="disc-tag">{TRANSLATION_TYPE_LABELS[n.translation_type] || n.translation_type}</li>);
  if (lang) {
    tags.push(
      <li key="lang" className="disc-tag is-lang" title={LANG_NAME[lang] || lang}>
        <span aria-hidden="true">{String(lang).toUpperCase()}</span><span className="sr-only">{LANG_NAME[lang] || lang}</span>
      </li>,
    );
  }
  if (!tags.length) return null;
  return <ul className={["disc-tags", className].filter(Boolean).join(" ")} aria-label="Features">{tags}</ul>;
}

/* ---------- featured strip ---------- */
const heroVariants = {
  hidden: { opacity: 0, y: 26, filter: "blur(10px)" },
  show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.9, ease: ease.out, delayChildren: 0.16, staggerChildren: 0.07 }, transitionEnd: { filter: "none" } },
};
const heroJacketVariants = {
  hidden: { opacity: 0, rotateY: -24, x: -26, scale: 0.9 },
  show: { opacity: 1, rotateY: 0, x: 0, scale: 1, transition: { ...springs.gentle, opacity: { duration: 0.5 } } },
};
const lineVariants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: ease.out } },
};
const sideVariants = {
  hidden: { opacity: 0, x: 28, filter: "blur(8px)" },
  show: (i) => ({ opacity: 1, x: 0, filter: "blur(0px)", transition: { duration: 0.8, ease: ease.out, delay: 0.35 + i * 0.12 }, transitionEnd: { filter: "none" } }),
};

function FeatureHero({ n, added, onAdd, label }) {
  const meta = metaLine(n);
  const reduced = useReducedMotion();
  return (
    <motion.article className="disc-hero" data-vt-card="" variants={heroVariants} initial={reduced ? false : "hidden"} animate="show" style={hueStyle(n)}>
      <div className="disc-hero-light" aria-hidden="true">
        {n.cover_url && <img className="disc-hero-backdrop" src={n.cover_url} alt="" decoding="async" />}
      </div>
      <div className="disc-hero-stage">
        <motion.div className="disc-hero-float" variants={heroJacketVariants}>
          <Link className="disc-hero-cover" to={`/n/${n.id}`} tabIndex={-1} aria-hidden="true">
            <Cover src={n.cover_url} title={n.title} author={n.author} tilt={10} />
          </Link>
        </motion.div>
      </div>
      <div className="disc-hero-copy">
        <motion.p className="disc-kicker" variants={lineVariants}><span className="disc-kicker-dot" aria-hidden="true" />{label}</motion.p>
        <motion.h2 className="disc-hero-title" variants={lineVariants}><Link to={`/n/${n.id}`}>{n.title}</Link></motion.h2>
        {n.author && <motion.p className="disc-hero-author" variants={lineVariants}>{n.author}</motion.p>}
        {n.description && <motion.p className="disc-hero-blurb" variants={lineVariants}>{n.description}</motion.p>}
        <motion.div variants={lineVariants}><FeatureTags n={n} /></motion.div>
        <motion.div className="disc-hero-actions" variants={lineVariants}>
          <AddButton n={n} added={added} onAdd={onAdd} variant="hero" />
          <Link className="btn btn-ghost lg disc-hero-open" to={`/n/${n.id}`}>
            Details<span className="sr-only"> about {n.title}</span><Icon name="arrowRight" size={17} />
          </Link>
        </motion.div>
        {meta && <motion.p className="disc-hero-meta" variants={lineVariants}>{meta}</motion.p>}
      </div>
    </motion.article>
  );
}

function FeatureSide({ n, index, added, onAdd }) {
  const meta = metaLine(n);
  const reduced = useReducedMotion();
  return (
    <motion.article className="disc-side" data-vt-card="" custom={index} variants={sideVariants} initial={reduced ? false : "hidden"} animate="show" style={hueStyle(n)}>
      <div className="disc-side-light" aria-hidden="true">
        {n.cover_url && <img className="disc-side-backdrop" src={n.cover_url} alt="" decoding="async" loading="lazy" />}
      </div>
      <Link className="disc-side-cover" to={`/n/${n.id}`} tabIndex={-1} aria-hidden="true">
        <Cover src={n.cover_url} title={n.title} author={n.author} tilt={9} />
      </Link>
      <div className="disc-side-copy">
        <h3 className="disc-side-title"><Link to={`/n/${n.id}`}>{n.title}</Link></h3>
        {n.author && <p className="disc-side-author">{n.author}</p>}
        {n.description && <p className="disc-side-blurb">{n.description}</p>}
        <FeatureTags n={n} className="is-compact" />
        <div className="disc-side-foot">
          {meta && <span className="disc-side-meta">{meta}</span>}
          <AddButton n={n} added={added} onAdd={onAdd} variant="side" />
        </div>
      </div>
    </motion.article>
  );
}

export function FeaturedStrip({ items, label, addedIds, onAdd }) {
  const [hero, ...rest] = items;
  if (!hero) return null;
  return (
    <section className={"disc-feature" + (rest.length ? "" : " is-solo")} aria-label={`Featured: ${label}`}>
      <FeatureHero n={hero} added={addedIds.has(hero.id)} onAdd={onAdd} label={label} />
      {rest.length > 0 && (
        <div className="disc-feature-side">
          {rest.map((n, i) => <FeatureSide key={n.id} n={n} index={i} added={addedIds.has(n.id)} onAdd={onAdd} />)}
        </div>
      )}
    </section>
  );
}

/* ---------- grid card ---------- */
export const DiscoverCard = forwardRef(function DiscoverCard(
  { n, delay, rise = 0, added, onAdd, animated, layoutDependency }, ref,
) {
  const reduced = useReducedMotion();
  const Tag = animated ? motion.li : "li";
  const Stage = animated ? motion.div : "div";
  const Body = animated ? motion.div : "div";
  const c = { delay };
  const meta = metaLine(n);
  // Past the motion cap a card arrives with the cheap CSS rise instead.
  return (
    <Tag ref={ref} className={"shelf-card disc-card" + (added ? " is-added" : "") + (animated ? "" : " rise")}
         style={animated ? undefined : { "--i": rise }} data-vt-card=""
         {...itemMotion(animated, layoutDependency, reduced)}>
      {/* Text first for keyboard and screen readers; CSS lifts the jacket above it. */}
      <Body className="shelf-card-body" {...(animated ? { variants: bodyVariants, custom: c } : {})}>
        <Link className="shelf-card-title" to={`/n/${n.id}`}>{n.title}</Link>
        {n.author && <p className="shelf-card-author">{n.author}</p>}
        <FeatureTags n={n} className="is-compact" />
        {meta && <p className="disc-meta">{meta}</p>}
      </Body>
      <Stage className="shelf-card-stage" {...(animated ? { variants: stageVariants, custom: c } : {})}>
        <div className="shelf-card-lift">
          <Link className="shelf-card-cover" to={`/n/${n.id}`} tabIndex={-1} aria-hidden="true">
            <Cover src={n.cover_url} title={n.title} author={n.author} tilt={8} />
          </Link>
          <div className="shelf-card-actions disc-card-actions">
            <AddButton n={n} added={added} onAdd={onAdd} variant="cover" />
          </div>
        </div>
      </Stage>
    </Tag>
  );
});

/* ---------- filters ---------- */
/* Choosing the checked option again clears the filter. */
function MenuOptions({ options, value, onPick }) {
  return options.map(([v, l]) => (
    <MenuItem key={v} {...menuItemProps(value === v)} selected={value === v} onClick={() => onPick(value === v ? "" : v)}>{l}</MenuItem>
  ));
}

function FilterPill({ label, icon, value, options, groups, onChange }) {
  const [open, setOpen] = useState(false);
  const { close, triggerProps, menuProps } = useMenu(open, setOpen, label);
  const all = groups ? groups.flatMap(g => g.options) : options;
  const selected = all.find(([v]) => v === value);
  const pick = (v) => { close(); onChange(v); };
  return (
    <div className={"disc-pill" + (value ? " is-on" : "")}>
      <Popover open={open} onClose={() => setOpen(false)} align="left" className={"disc-pop" + (groups ? " is-grouped" : "")} trigger={
        <button type="button" className={"filter-chip" + (value ? " on" : "")} {...triggerProps}
                onClick={() => setOpen(o => !o)}>
          <Icon name={icon} size={14} />
          {selected ? <><span className="sr-only">{label}: </span>{selected[1]}</> : label}
          {!value && <Icon name="chevronDown" size={13} />}
        </button>
      }>
        <div className="disc-menu" {...menuProps}>
          {groups
            ? groups.map(g => (
              <div className="disc-pop-group" key={g.label} role="group" aria-label={g.label}>
                <div className="menu-label" aria-hidden="true">{g.label}</div>
                <MenuOptions options={g.options} value={value} onPick={pick} />
              </div>
            ))
            : <MenuOptions options={options} value={value} onPick={pick} />}
        </div>
      </Popover>
      {value && (
        <button type="button" className="disc-pill-clear" aria-label={`Clear ${label}`} onClick={() => onChange("")}>
          <Icon name="x" size={12} sw={2.4} />
        </button>
      )}
    </div>
  );
}

function TogglePill({ label, icon, on, onToggle }) {
  return (
    <button type="button" className={"filter-chip disc-toggle" + (on ? " on" : "")} aria-pressed={on} onClick={onToggle}>
      <Icon name={icon} size={14} />
      {label}
      <span className="disc-toggle-tick" aria-hidden="true"><Icon name="check" size={11} sw={3} /></span>
    </button>
  );
}

/** The filter definitions, shared by the pills and the sheet. */
export function filterFields(filters, setParam) {
  return [
    { key: "lang", label: "Language", icon: "globe", value: filters.language, options: LANGS, set: v => setParam("lang", v) },
    { key: "tr", label: "Translation", icon: "feather", value: filters.translation, options: TRANSLATIONS, set: v => setParam("tr", v) },
    { key: "tag", label: "Genre", icon: "sparkles", value: filters.tag, groups: TAG_GROUPS, set: v => setParam("tag", v) },
    { key: "fresh", label: "Freshness", icon: "clock", value: filters.freshness, options: FRESHNESS, set: v => setParam("fresh", v) },
  ];
}

export function FilterBar({ filters, setParam, activeCount, onClearAll }) {
  return (
    <div className="disc-filters" role="group" aria-label="Filters">
      {filterFields(filters, setParam).map(f => (
        <FilterPill key={f.key} label={f.label} icon={f.icon} value={f.value} options={f.options} groups={f.groups} onChange={f.set} />
      ))}
      <TogglePill label="Has codex" icon="compass" on={filters.has_codex} onToggle={() => setParam("codex", !filters.has_codex)} />
      <TogglePill label="Has audio" icon="headphones" on={filters.has_audio} onToggle={() => setParam("audio", !filters.has_audio)} />
      {activeCount > 0 && (
        <button type="button" className="disc-clear" onClick={onClearAll}>
          <Icon name="x" size={13} sw={2.2} />{activeCount > 1 ? `Clear ${activeCount} filters` : "Clear filter"}
        </button>
      )}
    </div>
  );
}

/* Phones: one Filters button, active filters as removable pills, and a sheet. */
export function MobileFilters({ filters, setParam, activeCount, onClearAll, total, loading }) {
  const [open, setOpen] = useState(false);
  const fields = filterFields(filters, setParam);
  const active = [
    ...fields.filter(f => f.value).map(f => {
      const all = f.groups ? f.groups.flatMap(g => g.options) : f.options;
      const hit = all.find(([v]) => v === f.value);
      return { key: f.key, label: hit ? hit[1] : f.value, clearLabel: `Clear ${f.label}`, clear: () => f.set("") };
    }),
    ...(filters.has_codex ? [{ key: "codex", label: "Has codex", clearLabel: "Clear Has codex", clear: () => setParam("codex", false) }] : []),
    ...(filters.has_audio ? [{ key: "audio", label: "Has audio", clearLabel: "Clear Has audio", clear: () => setParam("audio", false) }] : []),
  ];
  return (
    <div className="disc-mfilters">
      <button type="button" className={"filter-chip disc-mfilters-open" + (activeCount ? " on" : "")} onClick={() => setOpen(true)} aria-haspopup="dialog">
        <Icon name="sliders" size={15} />Filters
        {activeCount > 0 && <span className="disc-mfilters-count">{activeCount}</span>}
      </button>
      {active.map(a => (
        <button key={a.key} type="button" className="filter-chip on disc-mfilters-chip" aria-label={a.clearLabel} onClick={a.clear}>
          {a.label}<Icon name="x" size={12} sw={2.4} />
        </button>
      ))}
      {open && (
        <Dialog title="Filters" icon="sliders" onClose={() => setOpen(false)}>
          <div className="disc-sheet">
            {fields.map(f => {
              const groups = f.groups || [{ label: null, options: f.options }];
              return (
                <fieldset className="disc-sheet-group" key={f.key}>
                  <legend className="disc-sheet-legend"><Icon name={f.icon} size={14} />{f.label}</legend>
                  {groups.map(g => (
                    <div className="disc-sheet-chips" key={g.label || "all"} role="group" aria-label={g.label || f.label}>
                      {g.label && <span className="disc-sheet-sub">{g.label}</span>}
                      {g.options.map(([v, l]) => (
                        <button key={v} type="button" className={"filter-chip" + (f.value === v ? " on" : "")} aria-pressed={f.value === v}
                                onClick={() => f.set(f.value === v ? "" : v)}>{l}</button>
                      ))}
                    </div>
                  ))}
                </fieldset>
              );
            })}
            <fieldset className="disc-sheet-group">
              <legend className="disc-sheet-legend"><Icon name="sparkles" size={14} />Features</legend>
              <div className="disc-sheet-chips">
                <TogglePill label="Has codex" icon="compass" on={filters.has_codex} onToggle={() => setParam("codex", !filters.has_codex)} />
                <TogglePill label="Has audio" icon="headphones" on={filters.has_audio} onToggle={() => setParam("audio", !filters.has_audio)} />
              </div>
            </fieldset>
          </div>
          <div className="disc-sheet-foot">
            <Button variant="ghost" onClick={onClearAll} disabled={!activeCount}>Clear all</Button>
            <Button variant="primary" onClick={() => setOpen(false)}>
              {loading ? "Show results" : `Show ${total.toLocaleString()} ${total === 1 ? "story" : "stories"}`}
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

/* ---------- loading ---------- */
export function FeatureSkeleton() {
  return (
    <div className="disc-feature is-skeleton" aria-hidden="true">
      <div className="disc-hero rise">
        <div className="disc-hero-stage"><div className="skeleton cover disc-skel-cover" /></div>
        <div className="disc-hero-copy">
          <div className="skeleton text" style={{ width: 120 }} />
          <div className="skeleton text disc-skel-title" />
          <div className="skeleton text" style={{ width: "40%" }} />
          <div className="skeleton text" style={{ width: "92%", marginTop: 18 }} />
          <div className="skeleton text" style={{ width: "84%" }} />
          <div className="skeleton text" style={{ width: "60%" }} />
        </div>
      </div>
      <div className="disc-feature-side">
        {[0, 1].map(i => (
          <div className="disc-side rise" key={i} style={{ "--i": i + 2 }}>
            <div className="skeleton cover disc-skel-side" />
            <div className="disc-side-copy">
              <div className="skeleton text" style={{ width: "70%" }} />
              <div className="skeleton text" style={{ width: "44%" }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
