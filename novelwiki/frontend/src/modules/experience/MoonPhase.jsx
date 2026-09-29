/* Tonight's moon, drawn at its real phase (synodic month from a known new
   moon) — a small, true detail that sets the hour for the reading room. */
import React, { useId, useMemo } from "react";

const SYNODIC = 29.530588853;
const KNOWN_NEW_MOON = Date.UTC(2000, 0, 6, 18, 14);

export function moonPhase(date = new Date()) {
  const days = (date.getTime() - KNOWN_NEW_MOON) / 86_400_000;
  const age = ((days % SYNODIC) + SYNODIC) % SYNODIC;
  const fraction = age / SYNODIC; // 0 new → .5 full → 1 new
  const illumination = (1 - Math.cos(fraction * 2 * Math.PI)) / 2;
  const names = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous", "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"];
  const name = names[Math.round(fraction * 8) % 8];
  return { fraction, illumination, name };
}

/* Terminator path for a unit moon of radius r centred at (r, r). */
function litPath(r, fraction) {
  const waxing = fraction < 0.5;
  const k = Math.cos(fraction * 2 * Math.PI); // 1 new, -1 full
  const rx = Math.abs(k) * r;
  // Outer limb on the lit side, terminator ellipse back.
  const sweepOuter = waxing ? 1 : 0;
  const sweepInner = (waxing ? k > 0 : k < 0) ? 0 : 1;
  return `M ${r} 0 A ${r} ${r} 0 0 ${sweepOuter} ${r} ${2 * r} A ${rx} ${r} 0 0 ${sweepInner} ${r} 0 Z`;
}

export function MoonPhase({ size = 180, className = "" }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const phase = useMemo(() => moonPhase(), []);
  const r = size / 2;
  return (
    <div className={["moon", className].filter(Boolean).join(" ")} style={{ width: size, height: size }}
         role="img" aria-label={`${phase.name}, ${Math.round(phase.illumination * 100)}% lit`}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} aria-hidden="true">
        <defs>
          <radialGradient id={`${id}lit`} cx="42%" cy="38%" r="70%">
            <stop offset="0" stopColor="oklch(0.99 0.012 90)" />
            <stop offset="0.7" stopColor="oklch(0.92 0.02 85)" />
            <stop offset="1" stopColor="oklch(0.8 0.03 80)" />
          </radialGradient>
          <radialGradient id={`${id}dark`} cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="oklch(0.36 0.03 255 / 0.55)" />
            <stop offset="1" stopColor="oklch(0.26 0.03 255 / 0.4)" />
          </radialGradient>
          <filter id={`${id}blur`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation={size / 90} />
          </filter>
        </defs>
        <circle cx={r} cy={r} r={r - 1} fill={`url(#${id}dark)`} />
        <path d={litPath(r - 1, phase.fraction)} transform="translate(1 1)" fill={`url(#${id}lit)`} filter={`url(#${id}blur)`} />
        <g opacity="0.14" fill="oklch(0.4 0.03 250)">
          <circle cx={r * 0.72} cy={r * 0.78} r={r * 0.16} />
          <circle cx={r * 1.25} cy={r * 1.2} r={r * 0.11} />
          <circle cx={r * 1.05} cy={r * 0.6} r={r * 0.07} />
          <circle cx={r * 0.8} cy={r * 1.35} r={r * 0.08} />
        </g>
      </svg>
    </div>
  );
}
