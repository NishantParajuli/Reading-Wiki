/* ============================================================
   Appearance — the showpiece.
   · Theme: two miniature scenes drawn in CSS, each scoped with its own
     data-theme so it always shows the real Tide / Pearl tokens. Choosing
     one spreads the new light from the pointer (transitionTheme).
   · Accent: sea-glass pebbles. The hue glides across the whole interface
     (--accent-h animated on <html>), then commits to the theme + account.
   · Ambient motion: living water / still / off (setAmbientMode).
   ============================================================ */
import React, { useEffect, useRef, useState } from "react";

import { identityApi } from "./api.js";
import { Group, SectionHead, centerOf, useRadioGroup } from "./AccountParts.jsx";
import { useAuth, useTheme } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Chip } from "../../components/ui.jsx";
import { animate, motion, springs, useReducedMotion } from "../../motion/index.js";
import { transitionTheme } from "../../motion/navigation.js";
import { setAmbientMode } from "../../atmosphere/Ambient.jsx";

const THEMES = [
  { id: "dark", name: "Tide", line: "Night ocean, moonlit ink" },
  { id: "light", name: "Pearl", line: "Morning shore, deep-sea ink" },
];

export const ACCENTS = [
  { hue: 192, name: "Sea glass" },
  { hue: 165, name: "Lagoon" },
  { hue: 245, name: "Abyss" },
  { hue: 295, name: "Amethyst" },
  { hue: 22, name: "Coral" },
  { hue: 75, name: "Lantern" },
  { hue: 140, name: "Kelp" },
];

const AMBIENT = [
  { id: "living", name: "Living water", line: "The tide drifts slowly behind every page." },
  { id: "still", name: "Still", line: "One calm frame of water. Nothing moves." },
  { id: "off", name: "Off", line: "A quiet gradient — lightest on battery." },
];

export function AppearanceSection() {
  return (
    <section className="acct-section" aria-labelledby="acct-h-appearance">
      <SectionHead id="acct-h-appearance" icon="palette" title="Appearance"
                   lead="Make Tideglass feel like your own — its light, its colour, and how the sea behind the pages moves." />
      <Group i={1} title="Theme" hint="Tide for night reading, Pearl for daylight. Your choice is remembered on this device.">
        <ThemePicker />
      </Group>
      <AccentGroup />
      <Group i={3} title="Ambient motion" hint="The living water behind every screen.">
        <AmbientPicker />
      </Group>
      <p className="acct-footnote rise" style={{ "--i": 4 }}>
        <Icon name="bookOpen" size={14} /> The reader's sepia and night tones live in the reader's Aa menu.
      </p>
    </section>
  );
}

/* ---------- Theme ---------- */
function ThemePicker() {
  const { theme, setTheme } = useTheme();
  const choose = (next, origin) => {
    if (next === theme) return;
    transitionTheme(() => {
      document.documentElement.setAttribute("data-theme", next);
      setTheme(next);
    }, origin);
  };
  const radio = useRadioGroup(THEMES.map(t => t.id), theme, (v, el) => choose(v, centerOf(el)));
  return (
    <div className="acct-themes" role="radiogroup" aria-label="Theme">
      {THEMES.map((t, i) => {
        const on = theme === t.id;
        return (
          <button key={t.id} type="button" className={"acct-theme" + (on ? " on" : "")} {...radio(t.id, i)}
                  onClick={(e) => choose(t.id, e.detail === 0 ? centerOf(e.currentTarget) : { x: e.clientX, y: e.clientY })}>
            {on && <motion.span layoutId="acct-theme-ring" className="acct-theme-ring" transition={springs.layout} aria-hidden="true" />}
            <ThemeScene theme={t.id} />
            <span className="acct-theme-foot">
              <span className="acct-theme-name">
                <b>{t.name}</b>
                <small>{t.line}</small>
              </span>
              <span className="acct-radio" aria-hidden="true"><Icon name="check" size={13} sw={2.6} /></span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* A miniature of the theme: sky, moon or sun, the sea, and a sliver of the
   interface floating on it. Tokens resolve inside its own data-theme. */
function ThemeScene({ theme }) {
  return (
    <span className="acct-scene" data-theme={theme} aria-hidden="true">
      <span className="sc-sky" />
      {theme === "dark" && <span className="sc-stars" />}
      <span className="sc-orb" />
      <span className="sc-glint" />
      <svg className="sc-sea" viewBox="0 0 320 120" preserveAspectRatio="none">
        <path className="sc-w1" d="M0 26 C40 16 76 34 118 25 S196 12 238 24 S296 34 320 22 V120 H0Z" />
        <path className="sc-w2" d="M0 50 C44 40 88 60 132 50 S214 38 256 50 S300 58 320 48 V120 H0Z" />
        <path className="sc-w3" d="M0 78 C38 70 84 88 126 79 S206 66 250 78 S298 88 320 76 V120 H0Z" />
      </svg>
      <span className="sc-ui">
        <span className="sc-island"><i /><i /><i /></span>
        <span className="sc-card">
          <span className="sc-cover" />
          <span className="sc-lines"><i /><i /><i /></span>
        </span>
      </span>
      <span className="sc-sheen" />
    </span>
  );
}

/* ---------- Accent ---------- */
const norm = (h) => ((h % 360) + 360) % 360;

function AccentGroup() {
  const { accentHue, setAccentHue } = useTheme();
  const { user, onUserUpdate } = useAuth();
  const reduced = useReducedMotion();
  const [picked, setPicked] = useState(accentHue);
  const [sync, setSync] = useState(null); // null | saving | saved | error
  const glide = useRef(null);
  const syncSeq = useRef(0);

  useEffect(() => { if (!glide.current) setPicked(accentHue); }, [accentHue]);
  // Leaving mid-glide still lands on the chosen hue.
  useEffect(() => () => {
    const g = glide.current;
    if (g) { g.controls.stop(); glide.current = null; setAccentHue(g.to); }
  }, [setAccentHue]);

  function pick(hue) {
    if (hue === picked) return;
    setPicked(hue);
    const from = glide.current ? glide.current.value : accentHue;
    if (glide.current) { glide.current.controls.stop(); glide.current = null; }
    if (reduced) setAccentHue(hue);
    else {
      const root = document.documentElement;
      const delta = norm(hue - from + 180) - 180;
      const g = { to: hue, value: from, controls: null };
      g.controls = animate(0, 1, {
        duration: 0.7, ease: [0.16, 1, 0.3, 1],
        onUpdate: (t) => { g.value = from + delta * t; root.style.setProperty("--accent-h", g.value.toFixed(2)); },
        onComplete: () => { if (glide.current === g) glide.current = null; setAccentHue(hue); },
      });
      glide.current = g;
    }
    // The hue is also saved to the account (prefs.appearance.accent_h).
    if (user) {
      const seq = ++syncSeq.current;
      setSync("saving");
      identityApi.updateMe({ prefs: { appearance: { accent_h: hue } } })
        .then(u => { onUserUpdate && onUserUpdate(u); if (seq === syncSeq.current) setSync("saved"); })
        .catch(() => { if (seq === syncSeq.current) setSync("error"); });
    }
  }

  const radio = useRadioGroup(ACCENTS.map(a => a.hue), picked, (hue) => pick(hue));
  const current = ACCENTS.find(a => a.hue === picked);
  const aside = (
    <div className="acct-accent-aside">
      <span className="acct-accent-now">{current ? current.name : `Custom · ${Math.round(picked)}°`}</span>
      <span className={"acct-sync" + (sync ? ` is-${sync}` : "")} role="status">
        {sync === "saving" && <><span className="acct-sync-dot" aria-hidden="true" />Saving to your account…</>}
        {sync === "saved" && <><Icon name="check" size={13} sw={2.2} />Saved to your account</>}
        {sync === "error" && <><Icon name="alert" size={13} />Couldn't save to your account; kept on this device</>}
      </span>
    </div>
  );
  return (
    <Group i={2} title="Accent colour" hint="The glow in buttons, progress and focus. It changes everywhere, instantly." aside={aside}>
      <div className="acct-pebbles" role="radiogroup" aria-label="Accent colour">
        {ACCENTS.map((a, i) => {
          const on = picked === a.hue;
          return (
            <button key={a.hue} type="button" className={"acct-pebble" + (on ? " on" : "")}
                    style={{ "--ph": a.hue }} title={a.name} {...radio(a.hue, i)}
                    aria-label={`Accent: ${a.name}`} onClick={() => pick(a.hue)}>
              {on && <motion.span layoutId="acct-pebble-pool" className="acct-pebble-pool" transition={springs.smooth} aria-hidden="true" />}
              <span className="acct-pebble-stone" aria-hidden="true" />
              <span className="acct-pebble-name" aria-hidden="true">{a.name}</span>
            </button>
          );
        })}
      </div>
    </Group>
  );
}

/* ---------- Ambient motion ---------- */
function readAmbient() {
  try { return localStorage.getItem("nw-ambient") || "living"; } catch { return "living"; }
}

function AmbientPicker() {
  const [mode, setMode] = useState(readAmbient);
  const reduced = useReducedMotion();
  useEffect(() => {
    const onChange = () => setMode(readAmbient());
    window.addEventListener("tg-ambient-change", onChange);
    return () => window.removeEventListener("tg-ambient-change", onChange);
  }, []);
  const choose = (next) => { setMode(next); setAmbientMode(next); };
  const radio = useRadioGroup(AMBIENT.map(a => a.id), mode, choose);
  return (
    <>
      <div className="acct-ambient" role="radiogroup" aria-label="Ambient motion">
        {AMBIENT.map((a, i) => {
          const on = mode === a.id;
          return (
            <button key={a.id} type="button" className={"acct-amb" + (on ? " on" : "")} data-mode={a.id}
                    {...radio(a.id, i)} onClick={() => choose(a.id)}>
              {on && <motion.span layoutId="acct-amb-ring" className="acct-amb-ring" transition={springs.layout} aria-hidden="true" />}
              <span className="acct-amb-swatch" aria-hidden="true">
                <svg className="acct-amb-waves" viewBox="0 0 400 80" preserveAspectRatio="none">
                  <path d="M0 26 C33 19 67 19 100 26 C133 33 167 33 200 26 C233 19 267 19 300 26 C333 33 367 33 400 26" />
                  <path d="M0 44 C33 36 67 36 100 44 C133 52 167 52 200 44 C233 36 267 36 300 44 C333 52 367 52 400 44" />
                  <path d="M0 61 C33 55 67 55 100 61 C133 67 167 67 200 61 C233 55 267 55 300 61 C333 67 367 67 400 61" />
                </svg>
              </span>
              <span className="acct-amb-text">
                <b>{a.name}</b>
                <small>{a.line}</small>
              </span>
            </button>
          );
        })}
      </div>
      <p className="acct-note">
        {reduced
          ? <><Chip tone="info" icon="moon">Reduced motion is on</Chip><span>Your device asks for less motion, so the water stays still whichever you choose.</span></>
          : <><Icon name="moon" size={14} /><span>When your device asks for reduced motion, the water always stays still.</span></>}
      </p>
    </>
  );
}
