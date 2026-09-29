/* ============================================================
   Auth parts — the pieces of the sign-in stage (AuthScreen.jsx).

   · Wordmark      "Tideglass" rises letter by letter out of the waterline;
                   its reflection is the same letters flipped into horizontal
                   strips that sway and glint like moonlit water (CSS only:
                   compositor transforms/opacity, collapses under reduced
                   motion). Letter pairs are kerned from canvas metrics, since
                   per-letter boxes lose the font's own kerning.
   · MorphHeight   the card's height follows its content on a spring
                   (motion value, no re-renders), so mode switches morph.
   · Fields        glyph-led inputs; the password keeps its label/input
                   nesting (label > span "Password" + input) and an animated
                   eye that draws its slash when the password is visible.
   · ProviderButton  glass pills with inline provider marks.
   · ThemeSwitch   Night ⇄ Dawn with the app's circular theme ripple.
   ============================================================ */
import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../../components/Icon.jsx";
import { useTheme } from "../../App.jsx";
import { transitionTheme } from "../../motion/navigation.js";
import { AnimatePresence, animate, motion, springs, useIsPresent, useMotionValue, useReducedMotion } from "../../motion/index.js";

/* ---------------- wordmark ---------------- */

const WM_FONT = 'italic 360 200px "Fraunces Variable"';

/* True once the display face can render `text` (or after `timeout`), so the
   hero never performs its entrance in a fallback serif. */
export function useFontReady(font = WM_FONT, text = "Tideglass", timeout = 1600) {
  const [ready, setReady] = useState(() => {
    if (typeof document === "undefined" || !document.fonts || typeof document.fonts.check !== "function") return true;
    try { return document.fonts.check(font, text); } catch { return true; }
  });
  useEffect(() => {
    if (ready) return undefined;
    let alive = true;
    const done = () => { if (alive) setReady(true); };
    const timer = setTimeout(done, timeout);
    document.fonts.load(font, text).then(done, done);
    return () => { alive = false; clearTimeout(timer); };
  }, [ready, font, text, timeout]);
  return ready;
}

/* Kerning per letter (em), measured once the display face has loaded. */
function useKerning(text) {
  const [kern, setKern] = useState(() => Array.from(text, () => 0));
  useEffect(() => {
    let alive = true;
    const measure = () => {
      if (!alive) return;
      let ctx = null;
      try { ctx = document.createElement("canvas").getContext("2d"); } catch { ctx = null; }
      if (!ctx) return;
      ctx.font = WM_FONT;
      if ("fontKerning" in ctx) ctx.fontKerning = "normal";
      const width = (s) => ctx.measureText(s).width;
      const chars = Array.from(text);
      const next = chars.map((ch, i) => (i === 0 ? 0
        : Math.round(((width(chars[i - 1] + ch) - width(chars[i - 1]) - width(ch)) / 200) * 1000) / 1000));
      if (next.some(Boolean)) setKern(next);
    };
    if (document.fonts && typeof document.fonts.load === "function") {
      document.fonts.load(WM_FONT, text).then(measure, measure);
    } else {
      measure();
    }
    return () => { alive = false; };
  }, [text]);
  return kern;
}

function Letters({ chars, kern }) {
  return chars.map((ch, i) => (
    <span className="wm-l" key={i} style={{ "--i": i, marginInlineStart: kern[i] ? `${kern[i]}em` : undefined }}>
      <span className="wm-g">{ch}</span>
    </span>
  ));
}

/* Fraunces' vertical metrics (em): the line box is set to BOX so the baseline
   sits exactly on its bottom edge — the waterline. Glyphs reach ASC above it. */
const BOX = 0.723;
const ASC = 0.978;

/* Now and then the wordmark catches the moonlight: a one-shot sweep toggled
   by a timer, so nothing animates (or repaints) while it rests. */
function useShine(ref, enabled, every = 11000, first = 3000) {
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return undefined;
    let reduced = false;
    try { reduced = !!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches; } catch { reduced = false; }
    if (reduced) return undefined;
    let clear = 0;
    let timer = 0;
    const shine = () => {
      if (document.hidden) return;
      el.setAttribute("data-shine", "");
      clearTimeout(clear);
      clear = setTimeout(() => el.removeAttribute("data-shine"), 2000);
    };
    const start = setTimeout(() => { shine(); timer = setInterval(shine, every); }, first);
    return () => { clearTimeout(start); clearInterval(timer); clearTimeout(clear); el.removeAttribute("data-shine"); };
  }, [ref, enabled, every, first]);
}

export function Wordmark({ text = "Tideglass", strips = 9, ready = true }) {
  const chars = useMemo(() => Array.from(text), [text]);
  const kern = useKerning(text);
  const band = ASC / strips;
  const ref = useRef(null);
  useShine(ref, ready);
  return (
    <div className="wm" ref={ref}>
      <h1 className="wm-title">
        <span className="sr-only">{text}</span>
        <span className="wm-stand" aria-hidden="true">
          {/* the glow wraps only the upright letters: static once risen, so its blur is cached */}
          <span className="wm-lit"><span className="wm-word"><Letters chars={chars} kern={kern} /></span></span>
          {/* the same letters seen through the water: dim, wavering, below the line */}
          <span className="wm-under"><Letters chars={chars} kern={kern} /></span>
        </span>
      </h1>
      <span className="wm-waterline" aria-hidden="true" />
      <div className="wm-reflection" aria-hidden="true">
        {Array.from({ length: strips }, (_, k) => (
          // Strip k is the k-th band below the waterline. Clip insets live in the
          // strip's own unflipped box, so each band is measured from its bottom.
          <span className="wm-strip" key={k} style={{
            "--k": k,
            "--clip-t": `${(BOX - (k + 1) * band).toFixed(4)}em`,
            "--clip-b": `${(k * band).toFixed(4)}em`,
          }}>
            <Letters chars={chars} kern={kern} />
          </span>
        ))}
      </div>
    </div>
  );
}

/* ---------------- brand orb ---------------- */

export function AuthBrandMark({ size = 34 }) {
  const id = useId().replace(/:/g, "");
  return (
    <span className="brand-mark auth-orb" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 40 40" width={size} height={size}>
        <defs>
          <radialGradient id={`${id}-f`} cx="32%" cy="26%" r="78%">
            <stop offset="0" style={{ stopColor: "oklch(0.97 0.04 var(--accent-h))" }} />
            <stop offset="0.45" style={{ stopColor: "var(--accent)" }} />
            <stop offset="1" style={{ stopColor: "var(--accent-2)" }} />
          </radialGradient>
          <clipPath id={`${id}-c`}><circle cx="20" cy="20" r="17" /></clipPath>
        </defs>
        <circle cx="20" cy="20" r="17" fill={`url(#${id}-f)`} />
        <g clipPath={`url(#${id}-c)`}>
          <path className="bm-wave bm-wave-1" d="M-6 24c5-4 9-4 14 0s9 4 14 0 9-4 14 0 9 4 14 0v20H-6z" fill="oklch(1 0 0 / 0.28)" />
          <path className="bm-wave bm-wave-2" d="M-6 28c5-3.5 9-3.5 14 0s9 3.5 14 0 9-3.5 14 0 9 3.5 14 0v20H-6z" fill="oklch(1 0 0 / 0.22)" />
        </g>
        <circle cx="20" cy="20" r="17" fill="none" stroke="oklch(1 0 0 / 0.45)" strokeWidth="1" />
        <circle cx="14" cy="13" r="3.2" fill="oklch(1 0 0 / 0.7)" />
      </svg>
    </span>
  );
}

/* ---------------- theme ---------------- */

export function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = (e) => {
    if (!setTheme) return;
    const next = dark ? "light" : "dark";
    const r = e.currentTarget.getBoundingClientRect();
    transitionTheme(() => {
      document.documentElement.setAttribute("data-theme", next);
      setTheme(next);
    }, { x: r.left + r.width / 2, y: r.top + r.height / 2 });
  };
  return (
    <button type="button" className="auth-theme" onClick={toggle} data-theme-now={theme}
            aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
      <span className="at-icons" aria-hidden="true">
        <span className="at-icon at-sun"><Icon name="sun" size={16} /></span>
        <span className="at-icon at-moon"><Icon name="moon" size={15} /></span>
      </span>
      <span className="at-label" aria-hidden="true">{dark ? "Dawn" : "Night"}</span>
    </button>
  );
}

/* ---------------- card morph ---------------- */

/* The card follows its content's height on a spring. Inner animations (a
   notice easing open) simply retarget it, so the card never snaps. */
export function MorphHeight({ className = "", children }) {
  const inner = useRef(null);
  const height = useMotionValue("auto");
  const reduce = useReducedMotion();
  useLayoutEffect(() => {
    const el = inner.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    let first = true;
    let controls = null;
    const ro = new ResizeObserver(() => {
      const next = el.offsetHeight;
      if (first || reduce) {
        first = false;
        controls?.stop();
        height.set(next);
        return;
      }
      controls?.stop();
      controls = animate(height, next, springs.smooth);
    });
    ro.observe(el);
    return () => { ro.disconnect(); controls?.stop(); };
  }, [height, reduce]);
  return (
    <motion.div className={className} style={{ height }}>
      <div ref={inner} className="auth-morph-inner">{children}</div>
    </motion.div>
  );
}

/* The form that is leaving (cross-fading out) stays visible but is inert and
   hidden from assistive tech, so only the arriving form can be reached. */
export const PresenceForm = React.forwardRef(function PresenceForm(props, ref) {
  const present = useIsPresent();
  return (
    <motion.form ref={ref} {...props}
                 inert={present ? undefined : ""} aria-hidden={present ? undefined : true} />
  );
});

/* ---------------- notices ---------------- */

const NOTICE_ICON = { error: "circleAlert", warn: "circleAlert", ok: "circleCheck", info: "sparkles" };

/* tone: "error" (role=alert) · "warn" · "ok" · "info" (role=status). */
export function AuthNotice({ tone = "info", children }) {
  const error = tone === "error";
  return (
    <motion.div className={`auth-notice is-${tone}`} role={error ? "alert" : "status"}
                initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.34, ease: [0.16, 1, 0.3, 1] }}>
      <div className="an-body">
        <Icon name={NOTICE_ICON[tone] || "circleCheck"} size={16} className="an-icon" />
        <span>{children}</span>
      </div>
    </motion.div>
  );
}

/* ---------------- fields ---------------- */

const GLYPHS = {
  mail: "M4 5.5h16a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 17V7A1.5 1.5 0 0 1 4 5.5zM3 7l9 6.2L21 7",
  at: "M12 15.6a3.6 3.6 0 1 0 0-7.2 3.6 3.6 0 0 0 0 7.2zM15.6 8.4v4.4a2.7 2.7 0 0 0 5.4 0V12a9 9 0 1 0-3.6 7.2",
};

export function Glyph({ name }) {
  if (!GLYPHS[name]) return <Icon name={name} size={17} className="auth-glyph" />;
  return (
    <svg className="auth-glyph" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {GLYPHS[name].split("M").filter(Boolean).map((seg, i) => <path key={i} d={"M" + seg} />)}
    </svg>
  );
}

/* Field note: a validation error or a quiet confirmation, easing in. */
export function FieldNote({ error, help }) {
  const text = error || help;
  return (
    <AnimatePresence initial={false}>
      {text && (
        <motion.span key={error ? "e" : "h"} className={error ? "field-error" : "field-help"}
                     initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                     transition={{ duration: 0.22 }}>
          {!error && <Icon name="check" size={12} sw={2.4} />}
          {text}
        </motion.span>
      )}
    </AnimatePresence>
  );
}

function EyeGlyph() {
  return (
    <svg className="pw-eye" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path className="pw-lid" d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle className="pw-pupil" cx="12" cy="12" r="2.9" />
      <path className="pw-slash" d="M4 4l16 16" pathLength="1" />
    </svg>
  );
}

export function PasswordInput({ value, onChange, placeholder, autoComplete, id }) {
  const [show, setShow] = useState(false);
  return (
    <span className="auth-control pw-wrap">
      <Glyph name="lock" />
      <input id={id} type={show ? "text" : "password"} value={value} placeholder={placeholder}
             autoComplete={autoComplete} onChange={e => onChange(e.target.value)} />
      <button type="button" className="pw-toggle" aria-label={show ? "Hide password" : "Show password"}
              data-shown={show ? "" : undefined} onClick={() => setShow(s => !s)} tabIndex={-1}>
        <EyeGlyph />
      </button>
    </span>
  );
}

/* ---------------- OAuth providers ---------------- */

const PROVIDER_NAMES = { google: "Google", discord: "Discord" };

function ProviderMark({ provider }) {
  if (provider === "google") {
    return (
      <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden="true">
        <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 8 3l5.7-5.7C34 6.1 29.3 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z" />
        <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 8 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
        <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
        <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.6-.4-3.9z" />
      </svg>
    );
  }
  if (provider === "discord") {
    return (
      <svg viewBox="0 0 127.14 96.36" width="20" height="16" aria-hidden="true">
        <path fill="#5865F2" d="M107.7 8.07A105.15 105.15 0 0 0 81.47 0a72.06 72.06 0 0 0-3.36 6.83 97.68 97.68 0 0 0-29.11 0A72.37 72.37 0 0 0 45.64 0a105.89 105.89 0 0 0-26.25 8.09C2.79 32.65-1.71 56.6.54 80.21a105.73 105.73 0 0 0 32.17 16.15 77.7 77.7 0 0 0 6.89-11.11 68.42 68.42 0 0 1-10.85-5.18c.91-.66 1.8-1.34 2.66-2a75.57 75.57 0 0 0 64.32 0c.87.71 1.76 1.39 2.66 2a68.68 68.68 0 0 1-10.87 5.19 77 77 0 0 0 6.89 11.1 105.25 105.25 0 0 0 32.19-16.14c2.64-27.38-4.51-51.11-18.9-72.15zM42.45 65.69C36.18 65.69 31 60 31 53s5-12.74 11.43-12.74S54 46 53.89 53s-5.05 12.69-11.44 12.69zm42.24 0C78.41 65.69 73.25 60 73.25 53s5-12.74 11.44-12.74S96.23 46 96.12 53s-5.04 12.69-11.43 12.69z" />
      </svg>
    );
  }
  return <Icon name="globe" size={17} />;
}

export function ProviderButton({ provider, pending, disabled, onClick }) {
  const name = PROVIDER_NAMES[provider] || (provider ? provider.charAt(0).toUpperCase() + provider.slice(1) : "");
  return (
    <button type="button" className="auth-provider" data-ripple onClick={onClick}
            disabled={disabled} aria-busy={pending || undefined}>
      <span className="pv-mark" aria-hidden="true">
        {pending ? <span className="btn-spinner" /> : <ProviderMark provider={provider} />}
      </span>
      <span className="pv-name">{name}</span>
    </button>
  );
}
