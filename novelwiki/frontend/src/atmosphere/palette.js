/* ============================================================
   Cover palettes. A book's atmosphere comes from its jacket: the dominant
   vivid hue, a companion hue, and how colourful the cover is overall.

   Same-origin covers (uploads, imports) are sampled from pixels. Covers on
   other sites usually block pixel reads (no CORS), so those — and books
   without covers — fall back to a stable hue pair derived from the title.
   The blurred cover "aura" layer shows the real jacket colours either way.
   ============================================================ */
import { coverHues } from "../lib/utils.js";
import { hueDistance, rgbToOklch } from "./color.js";

const cache = new Map();
const STORE_KEY = "tg-palettes-v1";

function loadStore() {
  try { return JSON.parse(sessionStorage.getItem(STORE_KEY) || "{}") || {}; } catch { return {}; }
}
const store = typeof window !== "undefined" ? loadStore() : {};
function persist(key, value) {
  store[key] = value;
  try { sessionStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch { /* quota / private mode */ }
}

export function titlePalette(title) {
  const [h1, h2] = coverHues(title || "Tideglass");
  return { h1, h2, chroma: 0.11, light: 0.5, source: "title" };
}

function sameOrigin(src) {
  try { return new URL(src, window.location.href).origin === window.location.origin; } catch { return false; }
}

function sample(img) {
  const w = 36, h = 54;
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, w, h);
  const { data } = ctx.getImageData(0, 0, w, h);
  const buckets = Array.from({ length: 24 }, () => ({ weight: 0, l: 0, c: 0, x: 0, y: 0 }));
  let lightSum = 0, chromaSum = 0, count = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 200) continue;
    const [L, C, H] = rgbToOklch(data[i], data[i + 1], data[i + 2]);
    lightSum += L; chromaSum += C; count += 1;
    if (C < 0.035) continue;
    const weight = C * C * (1.15 - Math.abs(L - 0.62));
    const b = buckets[Math.floor(H / 15) % 24];
    b.weight += weight; b.l += L * weight; b.c += C * weight;
    b.x += Math.cos((H * Math.PI) / 180) * weight;
    b.y += Math.sin((H * Math.PI) / 180) * weight;
  }
  if (!count) return null;
  const ranked = buckets
    .map((b) => (b.weight > 0 ? { weight: b.weight, h: ((Math.atan2(b.y, b.x) * 180) / Math.PI + 360) % 360, c: b.c / b.weight } : null))
    .filter(Boolean)
    .sort((a, b) => b.weight - a.weight);
  const averageLight = lightSum / count;
  const averageChroma = chromaSum / count;
  if (!ranked.length) {
    // A monochrome jacket: keep it quiet, tinted toward the theme accent.
    return { h1: 230, h2: 260, chroma: 0.03, light: averageLight, source: "image" };
  }
  const first = ranked[0];
  const second = ranked.find((b) => hueDistance(b.h, first.h) > 38) || { h: (first.h + 55) % 360 };
  return {
    h1: Math.round(first.h),
    h2: Math.round(second.h),
    chroma: Math.min(0.16, Math.max(0.05, averageChroma * 1.6 + first.c * 0.35)),
    light: averageLight,
    source: "image",
  };
}

/** Resolve a palette for a cover (cached). Never rejects. */
export function getPalette(src, title) {
  const key = src || `title:${title || ""}`;
  if (cache.has(key)) return cache.get(key);
  if (store[key]) { const hit = Promise.resolve(store[key]); cache.set(key, hit); return hit; }
  const fallback = titlePalette(title);
  if (!src || typeof window === "undefined" || !sameOrigin(src)) {
    const done = Promise.resolve(fallback);
    cache.set(key, done);
    return done;
  }
  const promise = new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.decoding = "async";
    const timer = setTimeout(() => resolve(fallback), 4000);
    img.onload = () => {
      clearTimeout(timer);
      try {
        const palette = sample(img) || fallback;
        persist(key, palette);
        resolve(palette);
      } catch {
        resolve(fallback);
      }
    };
    img.onerror = () => { clearTimeout(timer); resolve(fallback); };
    img.src = src;
  });
  cache.set(key, promise);
  return promise;
}
