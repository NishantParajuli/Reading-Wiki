/* ============================================================
   Library parts — the pieces of the collection, shared with Discover.

   · ShelfCard  a jacket on the shelf: tilting cover (the hero), quick
                actions that spring up on hover/focus (always shown on
                touch), a gold "new" tab, and the reading state as a slim
                glowing tideline. Cover link, resume link and shelf menu are
                sibling controls — nothing interactive nests in a link.
   · ShelfRow   the same book as an elegant list row.
   · CoverMorph shares a jacket between grid and list (layoutId), so
                toggling the view flies every cover to its new place.
   · SearchField / SortMenu / Tally / skeletons.
   Motion: cards rise from a soft blur in a capped cascade, FLIP when the
   shelf, search or sort changes, and sink into the tide when they leave.
   ============================================================ */
import React, { forwardRef, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Icon } from "../../components/Icon.jsx";
import { Cover, ProgressBar } from "../../components/ui.jsx";
import { MenuItem, Popover } from "../../components/overlay.jsx";
import { animate, ease, motion, springs, useReducedMotion } from "../../motion/index.js";
import { SHELF_LABELS, SHELF_ORDER } from "../../lib/constants.js";
import { fmtChapter, relativeTime } from "../../lib/utils.js";

/* Items past this index render without motion: huge libraries stay light. */
export const MOTION_CAP = 48;

const SHELF_ICON = { reading: "bookOpen", to_read: "bookmark", completed: "circleCheck" };

export function readPct(n) {
  const max = Number(n.max_chapter) || 0;
  const read = Number(n.max_chapter_read) || 0;
  return max > 0 ? Math.round(Math.min(100, (read / max) * 100)) : 0;
}

const cascadeDelay = (index) => 0.08 + Math.min(index, 14) * 0.05;

/* ---------- motion variants ---------- */
/* The item itself only handles leaving; its jacket and text arrive separately
   so a cover that is flying in from the other view never fades. */
export const itemVariants = {
  hidden: {},
  show: {},
  exit: {
    opacity: 0, scale: 0.84, y: 22, filter: "blur(10px)",
    transition: { duration: 0.34, ease: ease.in },
  },
};
export const stageVariants = {
  hidden: { opacity: 0, y: 30, scale: 0.95, filter: "blur(12px)" },
  show: (c) => ({
    opacity: 1, y: 0, scale: 1, filter: "blur(0px)",
    transition: { duration: 0.8, ease: ease.out, delay: c.delay },
    transitionEnd: { filter: "none" },
  }),
};
const stageMorphVariants = { hidden: {}, show: {} };
export const bodyVariants = {
  hidden: { opacity: 0, y: 12 },
  show: (c) => ({ opacity: 1, y: 0, transition: { duration: 0.6, ease: ease.out, delay: c.delay + 0.1 } }),
};

/** Motion props for one grid/list item (none past the cap). */
export function itemMotion(animated, layoutDependency) {
  if (!animated) return {};
  return {
    layout: "position", layoutDependency, variants: itemVariants,
    initial: "hidden", animate: "show", exit: "exit",
    transition: { layout: springs.layout },
  };
}

/* ---------- small pieces ---------- */
export function Highlight({ text, q }) {
  const source = String(text || "");
  const needle = String(q || "").trim().toLowerCase();
  if (!needle) return source;
  const lower = source.toLowerCase();
  const at = lower.length === source.length ? lower.indexOf(needle) : -1;
  if (at < 0) return source;
  return (
    <>
      {source.slice(0, at)}
      <mark className="lib-hit">{source.slice(at, at + needle.length)}</mark>
      {source.slice(at + needle.length)}
    </>
  );
}

function PlayGlyph() {
  return (
    <svg width="10" height="11" viewBox="0 0 10 11" aria-hidden="true" focusable="false">
      <path d="M1.2 1.1c0-.6.66-.97 1.17-.65l6.6 4.1c.48.3.48 1 0 1.3l-6.6 4.1c-.51.32-1.17-.05-1.17-.65z" fill="currentColor" />
    </svg>
  );
}

export function SortGlyph({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M4 7h11M4 12h8M4 17h5M18 5v14M15 16l3 3 3-3" />
    </svg>
  );
}

/** A figure that glides from its last value to the next (tabular, calm). */
export function Tally({ value }) {
  const reduced = useReducedMotion();
  const target = Number.isFinite(Number(value)) ? Number(value) : 0;
  const [shown, setShown] = useState(reduced ? target : 0);
  const from = useRef(reduced ? target : 0);
  useEffect(() => {
    if (reduced) { from.current = target; setShown(target); return undefined; }
    const controls = animate(from.current, target, {
      duration: 1.2, ease: ease.out,
      onUpdate: (v) => { from.current = v; setShown(Math.round(v)); },
    });
    return () => controls.stop();
  }, [target, reduced]);
  return <span className="tabular">{shown.toLocaleString()}</span>;
}

/** Wrap a jacket so it can fly between the grid and the list. */
function CoverMorph({ id, on, children }) {
  if (!on) return children;
  return (
    <motion.div className="cover-morph" layoutId={`lib-cover-${id}`} transition={springs.layout}>
      {children}
    </motion.div>
  );
}

export function NewBadge({ count }) {
  return (
    <span className="shelf-new">
      <b>{Number(count).toLocaleString()}</b> unread<span className="sr-only"> chapters</span>
    </span>
  );
}

/* ---------- search ---------- */
export const SearchField = forwardRef(function SearchField(
  { value, onChange, placeholder, label, shortcut = false, className = "" }, ref,
) {
  const local = useRef(null);
  const inputRef = ref || local;
  return (
    <div className={["search-box", "tg-search", className].filter(Boolean).join(" ")}>
      <Icon name="search" size={17} />
      <input ref={inputRef} value={value} onChange={(e) => onChange(e.target.value)}
             placeholder={placeholder} aria-label={label} enterKeyHint="search" autoComplete="off" spellCheck={false}
             onKeyDown={(e) => { if (e.key === "Escape" && value) { e.preventDefault(); onChange(""); } }} />
      {value
        ? (
          <button type="button" className="icon-btn plain tg-search-clear" aria-label="Clear search"
                  onClick={() => { onChange(""); if (inputRef.current) inputRef.current.focus(); }}>
            <Icon name="x" size={14} sw={2} />
          </button>
        )
        : shortcut && <kbd className="tg-search-kbd" aria-hidden="true">/</kbd>}
    </div>
  );
});

/** Focus `ref` when "/" is pressed outside a field (and no dialog is open). */
export function useSlashFocus(ref) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
      const t = e.target;
      if (t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      const el = ref.current;
      if (!el) return;
      e.preventDefault();
      el.focus();
      el.select();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ref]);
}

/* ---------- sort ---------- */
export function SortMenu({ value, options, onChange, label = "Sort by", className = "" }) {
  const [open, setOpen] = useState(false);
  const current = options.find(o => o.id === value) || options[0];
  return (
    <Popover open={open} onClose={() => setOpen(false)} className="tg-sort-pop" trigger={
      <button type="button" className={["tg-sort", className].filter(Boolean).join(" ")} aria-haspopup="true" aria-expanded={open}
              onClick={() => setOpen(o => !o)}>
        <SortGlyph />
        <span className="sr-only">{label}: </span>
        <span className="tg-sort-label">{current.label}</span>
        <Icon name="chevronDown" size={13} className="tg-sort-caret" />
      </button>
    }>
      <div className="menu-label">{label}</div>
      {options.map(o => (
        <MenuItem key={o.id} selected={o.id === current.id} onClick={() => { setOpen(false); onChange(o.id); }}>
          {o.label}
        </MenuItem>
      ))}
    </Popover>
  );
}

/* ---------- shelf menu ---------- */
function ShelfMenu({ n, open, onOpenChange, onMove, onRemove, variant = "cover" }) {
  return (
    <Popover open={open} onClose={() => onOpenChange(false)} className="shelf-pop" trigger={
      <button type="button" className={variant === "row" ? "icon-btn plain lib-row-menu" : "shelf-act shelf-act-menu"}
              aria-label="Shelf menu" aria-haspopup="true" aria-expanded={open}
              onClick={() => onOpenChange(!open)}>
        <Icon name="more" size={17} sw={2.6} />
      </button>
    }>
      <div className="menu-label">Shelf</div>
      {SHELF_ORDER.map(s => (
        <MenuItem key={s} icon={SHELF_ICON[s]} selected={n.shelf === s}
                  onClick={() => { onOpenChange(false); onMove(n, n.shelf === s ? "" : s); }}>
          {SHELF_LABELS[s]}
        </MenuItem>
      ))}
      <div className="menu-sep" />
      <MenuItem icon="x" danger onClick={() => { onOpenChange(false); onRemove(n); }}>
        Remove from library
      </MenuItem>
    </Popover>
  );
}

/* ---------- reading state ---------- */
export function ReadingState({ n, compact = false }) {
  const started = n.last_chapter != null;
  const done = n.shelf === "completed";
  const p = readPct(n);
  const when = n.last_read_at ? relativeTime(n.last_read_at) : "";
  const time = when && !compact
    ? <time className="shelf-state-when" dateTime={n.last_read_at} title={new Date(n.last_read_at).toLocaleString()}>{when}</time>
    : null;
  if (done || started) {
    return (
      <div className={"shelf-state" + (done ? " is-done" : "")}>
        <ProgressBar size="xs" value={p} tone={done ? "ok" : undefined} className="shelf-progress"
                     label={`Reading progress for ${n.title}`} />
        <div className="shelf-state-line">
          {done
            ? <span className="shelf-state-done"><Icon name="check" size={12} sw={2.6} /> Finished</span>
            : (
              <span className="shelf-state-ch">
                Ch. {fmtChapter(n.last_chapter)}
                {n.max_chapter ? <span className="shelf-state-of"> / {fmtChapter(n.max_chapter)}</span> : null}
              </span>
            )}
          {time}
        </div>
      </div>
    );
  }
  const count = Number(n.chapter_count) || 0;
  return (
    <div className="shelf-state is-unopened">
      <div className="shelf-state-line">
        <span>{count ? `${count.toLocaleString()} ${count === 1 ? "chapter" : "chapters"}` : "No chapters yet"}</span>
        {count > 0 && !compact && <span className="shelf-state-when">Unopened</span>}
      </div>
    </div>
  );
}

/* ---------- grid card ---------- */
export const ShelfCard = forwardRef(function ShelfCard(
  { n, index, q, animated, morph, layoutDependency, onMove, onRemove, onFocusBook }, ref,
) {
  const [menuOpen, setMenuOpen] = useState(false);
  const started = n.last_chapter != null;
  const resumeCh = started ? n.last_chapter : (n.min_chapter || 1);
  const canRead = (Number(n.chapter_count) || 0) > 0;
  const Tag = animated ? motion.li : "li";
  const Stage = animated ? motion.div : "div";
  const Body = animated ? motion.div : "div";
  const c = { delay: morph ? 0.18 : cascadeDelay(index) };
  const hover = onFocusBook
    ? { onPointerEnter: (e) => { if (e.pointerType === "mouse") onFocusBook(n); }, onPointerLeave: () => onFocusBook(null) }
    : {};
  return (
    <Tag ref={ref} className={"shelf-card" + (menuOpen ? " is-menu-open" : "")} data-vt-card=""
         {...itemMotion(animated, layoutDependency)} {...hover}>
      {/* Text first for keyboard and screen readers; CSS lifts the jacket above it. */}
      <Body className="shelf-card-body" {...(animated ? { variants: bodyVariants, custom: c } : {})}>
        <Link className="shelf-card-title" to={`/n/${n.id}`}><Highlight text={n.title} q={q} /></Link>
        {n.author && <p className="shelf-card-author"><Highlight text={n.author} q={q} /></p>}
        <ReadingState n={n} />
      </Body>
      <Stage className="shelf-card-stage" {...(animated ? { variants: morph ? stageMorphVariants : stageVariants, custom: c } : {})}>
        <div className="shelf-card-lift">
          <Link className="shelf-card-cover" to={`/n/${n.id}`} tabIndex={-1} aria-hidden="true">
            <CoverMorph id={n.id} on={animated}>
              <Cover src={n.cover_url} title={n.title} author={n.author} tilt={8} />
            </CoverMorph>
          </Link>
          {n.new_chapters > 0 && <NewBadge count={n.new_chapters} />}
          <div className="shelf-card-actions">
            {canRead && (
              <Link className="shelf-act shelf-act-read" to={`/n/${n.id}/read/${resumeCh}`}
                    aria-label={`${started ? "Resume" : "Start reading"} ${n.title}`}>
                <PlayGlyph />
                <span>{started ? "Resume" : "Start"}</span>
              </Link>
            )}
            <ShelfMenu n={n} open={menuOpen} onOpenChange={setMenuOpen} onMove={onMove} onRemove={onRemove} />
          </div>
        </div>
      </Stage>
    </Tag>
  );
});

/* ---------- list row ---------- */
const rowBodyVariants = {
  hidden: { opacity: 0, x: -10 },
  show: (c) => ({ opacity: 1, x: 0, transition: { duration: 0.5, ease: ease.out, delay: c.delay } }),
};

export const ShelfRow = forwardRef(function ShelfRow(
  { n, index, q, animated, morph, layoutDependency, onMove, onRemove }, ref,
) {
  const [menuOpen, setMenuOpen] = useState(false);
  const started = n.last_chapter != null;
  const resumeCh = started ? n.last_chapter : (n.min_chapter || 1);
  const canRead = (Number(n.chapter_count) || 0) > 0;
  const Tag = animated ? motion.li : "li";
  const Body = animated ? motion.div : "div";
  const c = { delay: (morph ? 0.12 : 0.06) + Math.min(index, 14) * 0.035 };
  const bodyMotion = animated ? { variants: rowBodyVariants, custom: c } : {};
  return (
    <Tag ref={ref} className={"lib-row" + (menuOpen ? " is-menu-open" : "")} data-vt-card=""
         {...itemMotion(animated, layoutDependency)}>
      <div className="lib-row-cover">
        <CoverMorph id={n.id} on={animated}>
          <Cover src={n.cover_url} title={n.title} author={n.author} />
        </CoverMorph>
      </div>
      <Body className="lib-row-main" {...bodyMotion}>
        <Link className="lib-row-title" to={`/n/${n.id}`}><Highlight text={n.title} q={q} /></Link>
        <p className="lib-row-sub">
          {n.author && <span className="lib-row-author"><Highlight text={n.author} q={q} /></span>}
          {n.new_chapters > 0 && <NewBadge count={n.new_chapters} />}
        </p>
      </Body>
      <Body className="lib-row-state" {...bodyMotion}>
        <ReadingState n={n} compact />
      </Body>
      <Body className="lib-row-shelf" {...bodyMotion}>
        {n.shelf
          ? <span className={`lib-shelf-tag is-${n.shelf}`}><Icon name={SHELF_ICON[n.shelf]} size={12} sw={2} />{SHELF_LABELS[n.shelf]}</span>
          : <span className="lib-shelf-tag is-none">No shelf</span>}
      </Body>
      <Body className="lib-row-time" {...bodyMotion}>
        {n.last_read_at
          ? <time dateTime={n.last_read_at} title={new Date(n.last_read_at).toLocaleString()}>{relativeTime(n.last_read_at)}</time>
          : <><span aria-hidden="true">—</span><span className="sr-only">Never opened</span></>}
      </Body>
      <div className="lib-row-actions">
        {canRead && (
          <Link className="icon-btn plain lib-row-read" to={`/n/${n.id}/read/${resumeCh}`}
                aria-label={`${started ? "Resume" : "Start reading"} ${n.title}`} title={started ? "Resume" : "Start reading"}>
            <PlayGlyph />
          </Link>
        )}
        <ShelfMenu n={n} variant="row" open={menuOpen} onOpenChange={setMenuOpen} onMove={onMove} onRemove={onRemove} />
      </div>
    </Tag>
  );
});

/* ---------- loading ---------- */
export function ShelfSkeleton({ view, count = 10 }) {
  if (view === "list") {
    return (
      <div className="lib-list is-skeleton" aria-hidden="true">
        {Array.from({ length: 6 }, (_, i) => (
          <div className="lib-row rise" key={i} style={{ "--i": i }}>
            <div className="lib-row-cover"><div className="skeleton cover" /></div>
            <div className="lib-row-main"><div className="skeleton text" style={{ width: `${62 - (i % 3) * 12}%` }} /><div className="skeleton text" style={{ width: "34%", marginTop: 8 }} /></div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="lib-grid is-skeleton" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div className="shelf-card rise" key={i} style={{ "--i": i }}>
          <div className="skeleton cover" />
          <div className="shelf-card-body">
            <div className="skeleton text" style={{ width: `${86 - (i % 3) * 14}%` }} />
            <div className="skeleton text" style={{ width: "48%" }} />
          </div>
        </div>
      ))}
    </div>
  );
}
