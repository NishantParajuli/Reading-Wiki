/* ============================================================
   Generated jackets for books without cover art.
   Deterministic per title: the same book always gets the same jacket.
   Four abstract motifs from the Tideglass world — tide under a moon,
   sea-glass shards, ripples, a horizon — in a hue pair hashed from the
   title. Purely decorative: the title is typeset as real text on top.
   ============================================================ */
import React, { useId, useMemo } from "react";
import { coverHues } from "../lib/utils.js";

function seeded(title) {
  let h = 2166136261;
  const s = String(title || "");
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  let a = h >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const c = (l, ch, h, a = 1) => `oklch(${l} ${ch} ${((h % 360) + 360) % 360}${a < 1 ? ` / ${a}` : ""})`;

function wavePath(y, amp, freq, phase, width = 200, height = 300) {
  let d = `M0 ${height} L0 ${y}`;
  for (let x = 0; x <= width; x += 8) {
    const yy = y + Math.sin((x / width) * Math.PI * 2 * freq + phase) * amp + Math.sin((x / width) * Math.PI * 5.3 + phase * 1.7) * amp * 0.35;
    d += ` L${x} ${yy.toFixed(1)}`;
  }
  return `${d} L${width} ${height} Z`;
}

function Tide({ id, h1, h2, r }) {
  const mx = 120 + r() * 50, my = 58 + r() * 34, mr = 16 + r() * 10;
  const waves = Array.from({ length: 4 }, (_, i) => ({
    d: wavePath(170 + i * 30 + r() * 10, 4 + r() * 5, 1 + r() * 1.4, r() * 6),
    fill: c(0.3 - i * 0.045, 0.085, h2 + i * 8, 0.9),
  }));
  return (
    <>
      <defs>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c(0.46, 0.1, h1)} />
          <stop offset="0.62" stopColor={c(0.28, 0.08, h2)} />
          <stop offset="1" stopColor={c(0.16, 0.05, h2)} />
        </linearGradient>
        <radialGradient id={`${id}m`}>
          <stop offset="0" stopColor={c(0.97, 0.05, h1 + 30)} />
          <stop offset="0.35" stopColor={c(0.9, 0.08, h1 + 30, 0.55)} />
          <stop offset="1" stopColor={c(0.9, 0.08, h1 + 30, 0)} />
        </radialGradient>
      </defs>
      <rect width="200" height="300" fill={`url(#${id}s)`} />
      <circle cx={mx} cy={my} r={mr * 3.2} fill={`url(#${id}m)`} opacity="0.55" />
      <circle cx={mx} cy={my} r={mr} fill={c(0.96, 0.04, h1 + 30)} />
      {Array.from({ length: 7 }, (_, i) => (
        <rect key={i} x={mx - (14 - i * 1.6) - r() * 6} y={176 + i * 9} width={(28 - i * 3.2) + r() * 10} height="1.6" rx="0.8" fill={c(0.95, 0.05, h1 + 30, 0.55 - i * 0.06)} />
      ))}
      {waves.map((w, i) => <path key={i} d={w.d} fill={w.fill} />)}
    </>
  );
}

function Shards({ id, h1, h2, r }) {
  const shards = Array.from({ length: 7 }, (_, i) => {
    const cx = 20 + r() * 160, cy = 40 + r() * 220, s = 30 + r() * 70, rot = r() * 180;
    const sides = 4 + Math.floor(r() * 2);
    const pts = Array.from({ length: sides }, (_, k) => {
      const a = (k / sides) * Math.PI * 2 + r() * 0.6;
      const rr = s * (0.55 + r() * 0.45);
      return `${(cx + Math.cos(a) * rr).toFixed(1)},${(cy + Math.sin(a) * rr).toFixed(1)}`;
    }).join(" ");
    return { pts, rot, cx, cy, hue: i % 2 ? h1 : h2, l: 0.55 + r() * 0.3, a: 0.28 + r() * 0.3 };
  });
  return (
    <>
      <defs>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={c(0.3, 0.07, h1)} />
          <stop offset="1" stopColor={c(0.15, 0.05, h2)} />
        </linearGradient>
      </defs>
      <rect width="200" height="300" fill={`url(#${id}s)`} />
      {shards.map((s, i) => (
        <polygon key={i} points={s.pts} transform={`rotate(${s.rot.toFixed(1)} ${s.cx.toFixed(1)} ${s.cy.toFixed(1)})`}
                 fill={c(s.l, 0.12, s.hue, s.a)} stroke={c(0.97, 0.03, s.hue, 0.35)} strokeWidth="0.8" />
      ))}
    </>
  );
}

function Ripples({ id, h1, h2, r }) {
  const cx = 60 + r() * 80, cy = 150 + r() * 90;
  return (
    <>
      <defs>
        <radialGradient id={`${id}s`} cx={cx / 200} cy={cy / 300} r="1">
          <stop offset="0" stopColor={c(0.5, 0.11, h1)} />
          <stop offset="0.6" stopColor={c(0.25, 0.08, h2)} />
          <stop offset="1" stopColor={c(0.16, 0.05, h2)} />
        </radialGradient>
      </defs>
      <rect width="200" height="300" fill={`url(#${id}s)`} />
      {Array.from({ length: 9 }, (_, i) => (
        <circle key={i} cx={cx} cy={cy} r={10 + i * (14 + r() * 5)} fill="none"
                stroke={c(0.9, 0.07, i % 2 ? h1 : h2 + 20, 0.42 - i * 0.035)} strokeWidth={1.6 - i * 0.12} />
      ))}
      <circle cx={cx} cy={cy} r="5" fill={c(0.97, 0.05, h1 + 20)} />
    </>
  );
}

function Horizon({ id, h1, h2, r }) {
  const hy = 176 + r() * 30, sr = 34 + r() * 20, sx = 70 + r() * 60;
  return (
    <>
      <defs>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c(0.22, 0.06, h2)} />
          <stop offset={(hy / 300).toFixed(2)} stopColor={c(0.52, 0.12, h1)} />
          <stop offset={(hy / 300 + 0.001).toFixed(3)} stopColor={c(0.26, 0.08, h2)} />
          <stop offset="1" stopColor={c(0.14, 0.05, h2)} />
        </linearGradient>
        <linearGradient id={`${id}u`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c(0.96, 0.06, h1 + 40)} />
          <stop offset="1" stopColor={c(0.78, 0.14, h1 + 10)} />
        </linearGradient>
        <clipPath id={`${id}c`}><rect width="200" height={hy} /></clipPath>
      </defs>
      <rect width="200" height="300" fill={`url(#${id}s)`} />
      <circle cx={sx} cy={hy} r={sr} fill={`url(#${id}u)`} clipPath={`url(#${id}c)`} />
      {Array.from({ length: 9 }, (_, i) => {
        const w = (sr * 2 - i * 6) * (0.8 + r() * 0.3);
        return <rect key={i} x={sx - w / 2} y={hy + 6 + i * 11} width={Math.max(6, w)} height={2.6 - i * 0.18} rx="1.3" fill={c(0.88, 0.1, h1 + 20, 0.6 - i * 0.055)} />;
      })}
    </>
  );
}

const MOTIFS = [Tide, Shards, Ripples, Horizon];

/* The title's size shrinks with its longest word, so words wrap whole
   instead of breaking mid-word on narrow jackets. */
function titleSize(title) {
  const longest = String(title || "").split(/\s+/).reduce((max, word) => Math.max(max, word.length), 0);
  return `${Math.min(13.5, 118 / Math.max(8, longest)).toFixed(2)}cqw`;
}

export function GeneratedCover({ title, author }) {
  const rawId = useId();
  const id = `gc${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;
  // Motifs are plain functions of a seeded generator; building the tree once
  // per title keeps every shape identical across re-renders.
  const art = useMemo(() => {
    const pick = seeded(title);
    const [h1, h2] = coverHues(title);
    const motif = MOTIFS[Math.floor(pick() * MOTIFS.length)];
    return motif({ id, h1, h2, r: seeded(`${title}::shapes`) });
  }, [title, id]);
  return (
    <div className="cover-ph" aria-hidden="true">
      <svg viewBox="0 0 200 300" preserveAspectRatio="xMidYMid slice" focusable="false">
        {art}
      </svg>
      <div className="cover-ph-text">
        <div>
          <div className="cover-ph-title" style={{ "--ph-size": titleSize(title) }}>{title || ""}</div>
          <div className="cover-ph-rule" />
        </div>
        {author ? <div className="cover-ph-author">{author}</div> : <span />}
      </div>
    </div>
  );
}
