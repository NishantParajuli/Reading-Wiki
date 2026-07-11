/* Small shared helpers. */

/* Deterministic per-title hues for generated cover placeholders: hash the title
   into two oklch hues so every placeholder is distinct but stable. */
export function coverHues(title) {
  let h = 0;
  const s = String(title || "");
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  const h1 = h % 360;
  const h2 = (h1 + 40 + (h >> 8) % 80) % 360;
  return [h1, h2];
}

export function relativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "";
  const s = Math.round((Date.now() - then) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 7) return `${d}d ago`;
  const w = Math.round(d / 7);
  if (w < 5) return `${w}w ago`;
  const mo = Math.round(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.round(d / 365)}y ago`;
}

export function fmtDuration(startIso, endIso) {
  if (!startIso || !endIso) return null;
  const ms = new Date(endIso) - new Date(startIso);
  if (isNaN(ms) || ms < 0) return null;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

/* Format a chapter number: 12, 12.5 */
export function fmtChapter(n) {
  if (n == null) return "";
  const f = Number(n);
  return Number.isInteger(f) ? String(f) : String(f);
}

/* Minutes-left estimate from word count at ~240 wpm. */
export function minutesLeft(wordCount, fractionRead = 0) {
  if (!wordCount) return null;
  const mins = Math.ceil((wordCount * (1 - fractionRead)) / 240);
  return mins < 1 ? 1 : mins;
}

export function timeGreeting(name) {
  const h = new Date().getHours();
  const part = h < 5 ? "Up late" : h < 12 ? "Morning" : h < 18 ? "Afternoon" : "Evening";
  return name ? `${part}, ${name}` : part;
}

export function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
