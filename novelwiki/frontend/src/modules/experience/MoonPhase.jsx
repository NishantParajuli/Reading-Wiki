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

/* Maria (the dark "seas") and craters, as fractions of the radius. */
const MARIA = [[0.72, 0.7, 0.3, 0.22, -20], [1.18, 0.86, 0.22, 0.17, 30], [0.98, 1.3, 0.26, 0.15, 10]];
const CRATERS = [[0.66, 1.34, 0.085], [1.34, 1.24, 0.06], [1.08, 0.5, 0.05], [0.48, 1.02, 0.045], [1.48, 0.8, 0.04]];

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
          {/* limb darkening: the disc dims toward its edge, like a sphere */}
          <radialGradient id={`${id}limb`} cx="50%" cy="50%" r="50%">
            <stop offset="0.62" stopColor="oklch(0.3 0.03 250 / 0)" />
            <stop offset="1" stopColor="oklch(0.3 0.03 250 / 0.32)" />
          </radialGradient>
          <radialGradient id={`${id}crater`} cx="42%" cy="38%" r="62%">
            <stop offset="0" stopColor="oklch(0.45 0.03 250 / 0.5)" />
            <stop offset="0.7" stopColor="oklch(0.5 0.03 250 / 0.22)" />
            <stop offset="1" stopColor="oklch(0.98 0.01 90 / 0.35)" />
          </radialGradient>
          <clipPath id={`${id}disc`}><circle cx={r} cy={r} r={r - 1} /></clipPath>
          <filter id={`${id}soft`} x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation={size / 90} />
          </filter>
          <filter id={`${id}mare`} x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation={size / 45} />
          </filter>
        </defs>
        <circle cx={r} cy={r} r={r - 1} fill={`url(#${id}dark)`} />
        {/* The blur softens only the terminator: the disc clips the outer limb crisp. */}
        <g clipPath={`url(#${id}disc)`}>
          <path d={litPath(r - 1, phase.fraction)} transform="translate(1 1)" fill={`url(#${id}lit)`} filter={`url(#${id}soft)`} />
          <g fill="oklch(0.55 0.03 250 / 0.2)" filter={`url(#${id}mare)`}>
            {MARIA.map(([cx, cy, rx, ry, rot], i) => (
              <ellipse key={i} cx={r * cx} cy={r * cy} rx={r * rx} ry={r * ry} transform={`rotate(${rot} ${r * cx} ${r * cy})`} />
            ))}
          </g>
          {CRATERS.map(([cx, cy, cr], i) => (
            <circle key={i} cx={r * cx} cy={r * cy} r={r * cr} fill={`url(#${id}crater)`} />
          ))}
          <circle cx={r} cy={r} r={r - 1} fill={`url(#${id}limb)`} />
        </g>
      </svg>
    </div>
  );
}
