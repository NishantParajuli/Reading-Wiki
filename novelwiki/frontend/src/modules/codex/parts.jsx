/* Small visual pieces shared by the Codex surfaces: the tide glyph (a glass
   orb whose water level is how far into the book the reader's boundary
   sits), a number that glides between values, and the orb hand-off used for
   the card → dossier shared-element transition. All decorative; every piece
   renders the real value immediately under reduced motion. */
import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { animate } from "../../motion/index.js";

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
function readReduced() {
  try { const mq = window.matchMedia(REDUCED_QUERY); return Boolean(mq && mq.matches); } catch { return false; }
}

/* prefers-reduced-motion, tolerant of environments without matchMedia. */
export function useReducedMotionPref() {
  const [reduced, setReduced] = useState(readReduced);
  useEffect(() => {
    let mq = null;
    try { mq = window.matchMedia(REDUCED_QUERY); } catch { mq = null; }
    if (!mq || typeof mq.addEventListener !== "function") return undefined;
    const onChange = () => setReduced(Boolean(mq.matches));
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/* Glass orb with a wave line at `level` (0..1). */
export function TideGlyph({ level = 0.5, size = 22, className = "" }) {
  const raw = useId();
  const id = `tg${raw.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const l = Math.min(0.88, Math.max(0.14, Number.isFinite(level) ? level : 0.5));
  const surface = 3.2 + (1 - l) * 17.6;
  return (
    <svg className={["cx-tide-glyph", className].filter(Boolean).join(" ")} width={size} height={size}
         viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <defs>
        <clipPath id={`${id}-clip`}><circle cx="12" cy="12" r="9.4" /></clipPath>
      </defs>
      <circle className="tg-glass" cx="12" cy="12" r="10.2" />
      <g clipPath={`url(#${id}-clip)`}>
        <g className="tg-water" style={{ transform: `translateY(${surface.toFixed(2)}px)` }}>
          <path className="tg-wave tg-wave-back" d="M-24 0.6q3-1.9 6 0t6 0 6 0 6 0 6 0 6 0 6 0 6 0V28H-24Z" />
          <path className="tg-wave" d="M-24 1.4q3-1.6 6 0t6 0 6 0 6 0 6 0 6 0 6 0 6 0V28H-24Z" />
        </g>
      </g>
      <ellipse className="tg-glint" cx="8.6" cy="7.4" rx="2.6" ry="1.5" />
    </svg>
  );
}

/* The hero tide gauge: a large glass sphere filled to the reader's boundary
   within the whole book, beside a tide staff (first chapter at the bottom,
   last at the top). The water rises into place on arrival and moves with the
   boundary. `readTo` marks trusted progress when the reader is looking back. */
export function TideOrb({ ceiling, min = 1, bookMax, readTo }) {
  const raw = useId();
  const id = `to${raw.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const span = Number(bookMax) - Number(min);
  const at = (value) => (span > 0 ? Math.min(1, Math.max(0, (Number(value) - Number(min)) / span)) : 1);
  const level = at(ceiling);
  const shown = Math.min(0.94, Math.max(0.06, level));
  const surface = 96 - shown * 192;
  const read = readTo != null ? Math.min(0.94, Math.max(0.06, at(readTo))) : shown;
  // Only mark trusted progress when it is visibly apart from the boundary.
  const lookingBack = readTo != null && Number(readTo) > Number(ceiling) && read - shown > 0.1;
  const crowdTop = shown > 0.86 || (lookingBack && read > 0.86);
  const crowdBottom = shown < 0.14;
  return (
    <div className={"cx-tide-orb" + (crowdTop ? " crowd-top" : "") + (crowdBottom ? " crowd-bottom" : "")}
         style={{ "--level": shown, "--read": read }} aria-hidden="true">
      <svg className="cx-to-svg" viewBox="-120 -120 240 240">
        <defs>
          <clipPath id={`${id}-c`}><circle r="97" /></clipPath>
          <radialGradient id={`${id}-halo`}><stop offset="0.55" style={{ stopColor: "var(--accent)", stopOpacity: 0.22 }} /><stop offset="1" style={{ stopColor: "var(--accent)", stopOpacity: 0 }} /></radialGradient>
          <radialGradient id={`${id}-glass`} cx="0.34" cy="0.26" r="0.8"><stop offset="0" style={{ stopColor: "white", stopOpacity: 0.16 }} /><stop offset="0.6" style={{ stopColor: "white", stopOpacity: 0.02 }} /><stop offset="1" style={{ stopColor: "var(--accent)", stopOpacity: 0.1 }} /></radialGradient>
          <linearGradient id={`${id}-water`} gradientUnits="userSpaceOnUse" x1="0" y1="-6" x2="0" y2="170"><stop offset="0" style={{ stopColor: "var(--accent)", stopOpacity: 0.92 }} /><stop offset="0.38" style={{ stopColor: "var(--accent-2)", stopOpacity: 0.62 }} /><stop offset="1" style={{ stopColor: "var(--bg-2)", stopOpacity: 0.95 }} /></linearGradient>
          <linearGradient id={`${id}-rim`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" style={{ stopColor: "white", stopOpacity: 0.5 }} /><stop offset="0.5" style={{ stopColor: "white", stopOpacity: 0.08 }} /><stop offset="1" style={{ stopColor: "var(--accent)", stopOpacity: 0.55 }} /></linearGradient>
          <radialGradient id={`${id}-shade`} cx="0.5" cy="0.38" r="0.62"><stop offset="0.72" style={{ stopColor: "black", stopOpacity: 0 }} /><stop offset="1" style={{ stopColor: "black", stopOpacity: 0.28 }} /></radialGradient>
        </defs>
        <circle className="to-halo" r="119" fill={`url(#${id}-halo)`} />
        <circle className="to-glass" r="100" fill={`url(#${id}-glass)`} />
        <g clipPath={`url(#${id}-c)`}>
          <g className="to-water" style={{ transform: `translateY(${surface.toFixed(1)}px)` }}>
            <path className="to-wave to-wave-back" d="M-300 -6 q25 -11 50 0 t50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 V220 H-300Z" />
            <path className="to-wave" d="M-300 0 q25 -8 50 0 t50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 V220 H-300Z" fill={`url(#${id}-water)`} />
            <path className="to-crest" d="M-300 0 q25 -8 50 0 t50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0 50 0" />
            <g className="to-caustics">
              <path d="M-90 34 q20 -6 40 0 t40 0 40 0 40 0 40 0" />
              <path d="M-110 70 q22 -7 44 0 t44 0 44 0 44 0 44 0" />
              <path d="M-80 108 q18 -5 36 0 t36 0 36 0 36 0" />
            </g>
          </g>
        </g>
        <circle className="to-shade" r="99" fill={`url(#${id}-shade)`} />
        <circle className="to-rim" r="100" stroke={`url(#${id}-rim)`} />
        <path className="to-spec" d="M-70 -52 A 86 86 0 0 1 -18 -84" />
        <ellipse className="to-glint" cx="-46" cy="-58" rx="9" ry="5" transform="rotate(-32 -46 -58)" />
      </svg>
      <div className="cx-to-staff">
        <span className="cx-to-end is-top">Ch. {bookMax}</span>
        <span className="cx-to-mark"><i />Ch. {ceiling}</span>
        {lookingBack && <span className="cx-to-mark is-read"><i />read · {readTo}</span>}
        <span className="cx-to-end is-bottom">Ch. {min}</span>
      </div>
    </div>
  );
}

/* A number that glides from its previous value (or up from zero on first
   view when `rise` is set). Tabular figures keep the layout still. */
export function Ticker({ value, rise = false, duration = 0.9, className = "" }) {
  const reduced = useReducedMotionPref();
  const numeric = typeof value === "number" && Number.isFinite(value);
  const [shown, setShown] = useState(() => (numeric && rise && !reduced ? 0 : value));
  const previous = useRef(numeric && rise && !reduced ? 0 : value);

  useEffect(() => {
    const from = Number(previous.current);
    previous.current = value;
    if (!numeric || reduced || !Number.isFinite(from) || from === value) { setShown(value); return undefined; }
    const controls = animate(from, value, {
      duration, ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setShown(Math.round(v)),
      onComplete: () => setShown(value),
    });
    return () => controls.stop();
  }, [value, numeric, reduced, duration]);

  const text = typeof shown === "number" ? shown.toLocaleString() : shown;
  return <span className={["tabular", className].filter(Boolean).join(" ")}>{text}</span>;
}

/* ---------- orb hand-off (card → dossier) ----------
   The clicked card's orb and the dossier's hero orb share one view-transition
   name for a single navigation, so the orb flies into place. Only one element
   ever holds the name; it is released shortly after the transition. */
const MORPH_NAME = "cx-orb";
let named = null;
let releaseTimer = 0;

function canMorph() {
  return typeof document !== "undefined" && typeof document.startViewTransition === "function";
}

export function claimMorph(el) {
  if (!el || !canMorph()) return false;
  if (named && named !== el) named.style.viewTransitionName = "";
  el.style.viewTransitionName = MORPH_NAME;
  named = el;
  clearTimeout(releaseTimer);
  releaseTimer = setTimeout(() => {
    if (named) named.style.viewTransitionName = "";
    named = null;
  }, 1400);
  return true;
}

/* Hero side of the hand-off: name the orb during the commit that renders it
   (layout effect), so the transition's new snapshot already contains it.
   `token` is unique per navigation (the location key), or null for none. */
export function useMorphTarget(token) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    if (token != null && ref.current) claimMorph(ref.current);
  }, [token]);
  return ref;
}
