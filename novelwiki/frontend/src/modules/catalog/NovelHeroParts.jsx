/* ============================================================
   Novel hero parts — the pieces NovelHeader composes:
     · useArrival       how we got here (direct load, a page morph, or a
                        tab switch inside the same book) → which entrance
                        choreography runs
     · HeroFacts        the editorial spec strip (chapters, range, language…)
     · ExpandableText   the synopsis, clamped, opening with a height tide
     · Tideline         reading progress across the whole book: read water
                        lit, bookmarks as glowing pins, volumes as notches
     · NovelKebab       overflow menu (edit, copy link, remove, delete)
   Everything shown is real data from the novel, TOC and bookmarks.
   ============================================================ */
import React, { useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { catalogApi } from "./api.js";
import { readingApi } from "../reading/api.js";
import { groupToc } from "../reading/index.js";
import { Icon } from "../../components/Icon.jsx";
import { Popover, MenuItem } from "../../components/overlay.jsx";
import { useToast } from "../../components/toast.jsx";
import { NumberTicker } from "../../motion/NumberTicker.jsx";
import { STATUS_TAG_LABELS, TRANSLATION_TYPE_LABELS, VIS_LABELS } from "../../lib/constants.js";

/* ---------- arrival ---------- */
/** "direct" (first paint / hard load), or the view-transition type that
 *  mounted us ("page", "pop", "novel-tab"…). Read once, at mount. */
export function useArrival() {
  const [arrival] = useState(() => {
    if (typeof document === "undefined") return "direct";
    return document.documentElement.dataset.vt || "direct";
  });
  return arrival;
}

/* ---------- formatting ---------- */
export function fmtNum(n) {
  if (n == null || n === "") return "";
  const f = Number(n);
  if (!Number.isFinite(f)) return String(n);
  return Number.isInteger(f) ? f.toLocaleString() : String(f);
}

let languageNames = null;
export function languageName(code) {
  if (!code) return null;
  try {
    if (!languageNames) languageNames = new Intl.DisplayNames(["en"], { type: "language" });
    const name = languageNames.of(code);
    return name && name !== code ? name : code.toUpperCase();
  } catch {
    return code.toUpperCase();
  }
}

/** Display size for the title: short titles go enormous, long ones stay graceful. */
export function titleScale(title) {
  const n = String(title || "").length;
  if (n <= 22) return "t-xl";
  if (n <= 42) return "t-lg";
  if (n <= 80) return "t-md";
  return "t-sm";
}

/** Status + genre tags as an editorial eyebrow ("Ongoing · Fantasy · Mystery"). */
export function tagLine(novel, max = 3) {
  const tags = (novel.status_tags || []).map(t => STATUS_TAG_LABELS[t] || t);
  return tags.slice(0, max);
}

const VIS_ICON = { private: "lock", public: "users", global: "globe" };

/* ---------- data ---------- */
/** Bookmarks as a shared query so the hero's tideline and the Overview list agree. */
export function useBookmarksQuery(novelId) {
  return useQuery({
    queryKey: ["bookmarks", Number(novelId)],
    queryFn: () => readingApi.bookmarks(novelId),
    enabled: novelId != null,
    staleTime: 0,
  });
}

/* ---------- facts ---------- */
export function HeroFacts({ novel, animate, compact, baseIndex = 0 }) {
  const facts = [];
  const count = novel.chapter_count || 0;
  facts.push({
    key: "chapters", label: "Chapters",
    value: animate && !compact ? <NumberTicker value={count} duration={1.3} /> : fmtNum(count),
  });
  if (novel.max_chapter != null && count > 0) {
    facts.push({ key: "range", label: "Range", value: <>{fmtNum(novel.min_chapter)}<span className="nh-dash">–</span>{fmtNum(novel.max_chapter)}</> });
  }
  const lang = languageName(novel.original_language);
  if (lang) facts.push({ key: "lang", label: "Language", value: lang });
  const tt = novel.translation_type ? TRANSLATION_TYPE_LABELS[novel.translation_type] : null;
  if (tt) facts.push({ key: "tt", label: "Edition", value: tt });
  if (novel.visibility) {
    facts.push({
      key: "vis", label: "Visibility",
      value: <><Icon name={VIS_ICON[novel.visibility] || "globe"} size={compact ? 12 : 14} sw={1.9} />{VIS_LABELS[novel.visibility] || novel.visibility}</>,
    });
  }
  return (
    <dl className={"nh-facts" + (compact ? " is-compact" : "")}>
      {facts.map((f, i) => (
        <div key={f.key} className={"nh-fact" + (animate ? " rise" : "")} style={animate ? { "--i": baseIndex + i } : undefined}>
          <dt>{f.label}</dt>
          <dd>{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ---------- synopsis ---------- */
export function ExpandableText({ text, lines = 3, className = "", style }) {
  const id = useId();
  const textRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [metrics, setMetrics] = useState({ full: 0, overflows: text.length > 220 });

  useLayoutEffect(() => {
    const el = textRef.current;
    if (!el) return undefined;
    const measure = () => {
      const full = el.offsetHeight;
      if (!full) return;   // no layout (tests, hidden) — keep the length heuristic
      const lh = parseFloat(getComputedStyle(el).lineHeight) || 26;
      setMetrics({ full, overflows: full > lh * lines + 6 });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text, lines]);

  const expandable = metrics.overflows;
  return (
    <div className={["nh-desc", open ? "is-open" : "", expandable ? "can-expand" : "", className].filter(Boolean).join(" ")} style={style}>
      <div className="nh-desc-clip" id={id} style={{ "--full": `${metrics.full}px`, "--lines": lines }}>
        <div ref={textRef} className="nh-desc-text">
          {text.split(/\n\s*\n/).map((para, i) => <p key={i}>{para}</p>)}
        </div>
      </div>
      {expandable && (
        <button type="button" className="nh-more" aria-expanded={open} aria-controls={id} onClick={() => setOpen(o => !o)}>
          <span>{open ? "Less" : "More"}</span>
          <Icon name="chevronDown" size={14} sw={2} />
        </button>
      )}
    </div>
  );
}

/* ---------- tideline ---------- */
export function Tideline({ novel, bookmarks, toc, compact, animate }) {
  const min = Number(novel.min_chapter ?? 1);
  const max = Number(novel.max_chapter ?? min);
  const span = max - min;
  const pos = (n) => (span > 0 ? Math.min(1, Math.max(0, (Number(n) - min) / span)) : 1);

  const progress = novel.progress || {};
  const maxRead = progress.max_chapter_read || 0;
  const started = progress.last_chapter != null;
  const current = started ? Number(progress.last_chapter) : null;
  const pct = novel.max_chapter ? Math.round(Math.min(100, (maxRead / novel.max_chapter) * 100)) : 0;
  // Chapters beyond your furthest read (the API's `new_chapters`): unread, not "new".
  const unread = novel.max_chapter != null && maxRead > 0 ? Math.max(0, Math.round(novel.max_chapter - maxRead)) : 0;
  const lit = maxRead > 0 ? pos(maxRead) : 0;

  const volumes = useMemo(() => {
    if (!toc || !toc.length) return [];
    return groupToc(toc).filter(n => n.type === "vol" && n.chapters.length)
      .map(n => ({ label: n.label, start: Number(n.chapters[0].number) }))
      .filter(v => v.start > min);
  }, [toc, min]);

  const marks = (bookmarks || []).filter(b => b && b.chapter != null)
    .map(b => ({ id: b.id, chapter: Number(b.chapter), note: b.note }))
    .sort((a, b) => a.chapter - b.chapter);

  // Pins that arrive with late data pop in without waiting out the fill.
  const bornAt = useRef(Date.now());
  const pinDelays = useRef(new Map());
  const pinDelay = (key, i) => {
    if (!pinDelays.current.has(key)) {
      const sinceArrival = Date.now() - bornAt.current;
      pinDelays.current.set(key, Math.max(0, 1700 - sinceArrival) + i * 110);
    }
    return `${pinDelays.current.get(key)}ms`;
  };

  const moonAt = current != null ? pos(current) : null;
  const edge = moonAt == null ? "mid" : moonAt < 0.1 ? "start" : moonAt > 0.9 ? "end" : "mid";
  const status = started
    ? `${pct}% read · ${unread > 0 ? `${unread.toLocaleString()} unread` : "caught up"}`
    : "Not started yet";
  const valueText = started
    ? `${status}${current != null ? `. You are at chapter ${fmtNum(current)} of ${fmtNum(max)}` : ""}${marks.length ? `. ${marks.length} bookmark${marks.length === 1 ? "" : "s"}` : ""}.`
    : `Not started yet. ${fmtNum(novel.chapter_count)} chapters.`;

  return (
    <div className={"tl" + (compact ? " is-compact" : "") + (animate ? " is-arriving" : "")}>
      <div className="tl-track" role="progressbar" aria-label="Reading progress"
           aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-valuetext={valueText}>
        <span className="tl-bed" aria-hidden="true" />
        {lit > 0 && <span className="tl-water" aria-hidden="true" style={{ "--p": lit }} />}
        {volumes.map((v, i) => (
          <span key={v.label + i} className="tl-vol" aria-hidden="true" title={v.label}
                style={{ left: `${pos(v.start) * 100}%` }} />
        ))}
        {marks.map((m, i) => (
          <span key={m.id ?? i} className="tl-mark" aria-hidden="true"
                data-label={`Ch. ${fmtNum(m.chapter)}${m.note ? ` · ${m.note}` : ""}`}
                style={{ left: `${pos(m.chapter) * 100}%`, "--pin-delay": pinDelay(m.id ?? `c${m.chapter}`, i) }} />
        ))}
        {moonAt != null && (
          <span className={"tl-moon is-" + edge} aria-hidden="true" style={{ left: `${moonAt * 100}%` }}>
            <span className="tl-moon-orb" />
            {!compact && <span className="tl-moon-label">You are here · Ch. {fmtNum(current)}</span>}
          </span>
        )}
      </div>
      <div className="tl-scale">
        <span className="tl-end mono">Ch. {fmtNum(min)}</span>
        <span className="tl-status">{status}</span>
        <span className="tl-end mono">Ch. {fmtNum(max)}</span>
      </div>
    </div>
  );
}

/* ---------- overflow menu ---------- */
export function NovelKebab({ novel, canEdit, onDelete }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();
  const qc = useQueryClient();

  async function removeFromLibrary() {
    setOpen(false);
    try {
      await catalogApi.removeFromLibrary(novel.id);
      qc.invalidateQueries({ queryKey: ["novels"] });
      toast(`Removed “${novel.title}” from your library.`, { tone: "ok" });
      navigate("/library");
    } catch (e) {
      toast(e.message || "Couldn't remove it.", { tone: "danger" });
    }
  }

  return (
    <Popover open={open} onClose={() => setOpen(false)} className="nh-menu" trigger={
      <button type="button" className="icon-btn nh-kebab" aria-label="More actions" aria-expanded={open}
              onClick={() => setOpen(o => !o)}>
        <Icon name="more" size={18} sw={2.4} />
      </button>
    }>
      {canEdit && <MenuItem icon="edit" onClick={() => { setOpen(false); navigate(`/n/${novel.id}/manage`); }}>Edit novel</MenuItem>}
      <MenuItem icon="link" onClick={() => {
        setOpen(false);
        navigator.clipboard.writeText(window.location.origin + `/n/${novel.id}`)
          .then(() => toast("Link copied.", { tone: "ok" }))
          .catch(() => toast("Couldn't copy the link.", { tone: "danger" }));
      }}>Copy link</MenuItem>
      <MenuItem icon="x" onClick={removeFromLibrary}>Remove from library</MenuItem>
      {canEdit && (
        <>
          <div className="menu-sep" />
          <MenuItem icon="trash" danger onClick={() => { setOpen(false); onDelete(); }}>Delete novel…</MenuItem>
        </>
      )}
    </Popover>
  );
}
