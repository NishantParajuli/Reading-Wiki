/* ============================================================
   The add-to-library flight.

   A clone of the book's jacket lifts off its card, arcs across the room —
   trailing a few motes of sea-glass light — and drops into the Library
   destination in the shell (the island on desktop, the dock on phones),
   which answers with a ripple and a small pulse.

   Pure decoration layered over the real action: the request is started
   before this runs and never waits on it; every DOM query is guarded (the
   destination may be hidden or absent); nothing happens under
   prefers-reduced-motion or without the Web Animations API; every node it
   creates removes itself.
   ============================================================ */
import { prefersReducedMotion } from "../../motion/navigation.js";

const DESTINATIONS = ['.dock a[href="/library"]', '.island a[href="/library"]'];

function onScreen(el) {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
    && r.top < window.innerHeight && r.left < window.innerWidth;
}

/** The Library link the reader can currently see, or null. */
export function libraryDestination() {
  for (const selector of DESTINATIONS) {
    let el = null;
    try { el = document.querySelector(selector); } catch { el = null; }
    if (el && onScreen(el)) return el;
  }
  return null;
}

const lerp = (a, b, t) => a + (b - a) * t;
const easeInOutSine = (t) => -(Math.cos(Math.PI * t) - 1) / 2;
const easeOutCubic = (t) => 1 - (1 - t) ** 3;

function layer(className, rect) {
  const el = document.createElement("span");
  el.className = className;
  el.setAttribute("aria-hidden", "true");
  if (rect) Object.assign(el.style, { left: `${rect.x}px`, top: `${rect.y}px` });
  document.body.appendChild(el);
  return el;
}

function pulse(target) {
  const r = target.getBoundingClientRect();
  const center = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  const glow = layer("tg-fly-glow", center);
  const ring = layer("tg-fly-ring", center);
  const done = (el) => () => el.remove();
  glow.animate(
    [{ opacity: 0.85, transform: "translate(-50%, -50%) scale(0.35)" }, { opacity: 0, transform: "translate(-50%, -50%) scale(1.5)" }],
    { duration: 720, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "forwards" },
  ).finished.then(done(glow), done(glow));
  ring.animate(
    [{ opacity: 0.95, transform: "translate(-50%, -50%) scale(0.45)" }, { opacity: 0, transform: "translate(-50%, -50%) scale(2.1)" }],
    { duration: 820, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "forwards" },
  ).finished.then(done(ring), done(ring));
  target.animate(
    [{ transform: "scale(1)" }, { transform: "scale(1.16)", offset: 0.34 }, { transform: "scale(0.96)", offset: 0.68 }, { transform: "scale(1)" }],
    { duration: 640, easing: "cubic-bezier(0.3, 0.7, 0.4, 1)" },
  );
  setTimeout(() => { glow.remove(); ring.remove(); }, 1600);
}

/**
 * Fly `source` (a jacket element) into the Library destination.
 * Returns immediately; safe to call with anything.
 */
export function flyToLibrary(source) {
  try {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    if (!source || !source.isConnected || typeof source.animate !== "function") return;
    if (prefersReducedMotion()) return;
    const target = libraryDestination();
    if (!target) return;
    const from = source.getBoundingClientRect();
    const to = target.getBoundingClientRect();
    if (!from.width || !from.height) return;

    const clone = source.cloneNode(true);
    clone.removeAttribute("data-vt-cover");
    clone.removeAttribute("data-vt-hero");
    clone.removeAttribute("data-tilt");
    clone.removeAttribute("data-tilting");
    clone.setAttribute("aria-hidden", "true");
    clone.classList.add("tg-fly");
    Object.assign(clone.style, {
      position: "fixed", left: `${from.left}px`, top: `${from.top}px`,
      width: `${from.width}px`, height: `${from.height}px`, margin: "0",
      transform: "none", viewTransitionName: "none",
    });
    document.body.appendChild(clone);

    // The arc: a straight glide eased toward the destination, lifted by a
    // bump that peaks mid-flight — up and over into the island, or a toss
    // down into the dock. The bump shrinks until the apex stays on screen.
    const x0 = from.left + from.width / 2;
    const y0 = from.top + from.height / 2;
    const x1 = to.left + to.width / 2;
    const y1 = to.top + to.height / 2;
    const distance = Math.hypot(x1 - x0, y1 - y0);
    const dir = x1 >= x0 ? 1 : -1;
    const endScale = Math.max(0.06, 24 / from.width);
    const steps = 36;
    // Up into the island: decelerate as it arrives. Down into the dock:
    // fall with gravity, so the bump reads as a toss.
    const fall = y1 > y0 ? (t) => t * t : easeOutCubic;
    const point = (t, bump) => ({
      x: lerp(x0, x1, easeInOutSine(t)),
      y: lerp(y0, y1, fall(t)) - bump * Math.sin(Math.PI * t),
    });
    // lift a touch, then shrink steadily on the way home
    const scaleAt = (t) => (t < 0.14
      ? 1 + 0.07 * Math.sin((t / 0.14) * (Math.PI / 2))
      : lerp(1.07, endScale, easeInOutSine((t - 0.14) / 0.86)));
    let bump = Math.min(170, distance * 0.32 + 40);
    for (let i = 0; i < 16; i++) {
      let top = Infinity;
      for (let s = 0; s <= steps; s++) {
        const t = s / steps;
        top = Math.min(top, point(t, bump).y - (from.height / 2) * scaleAt(t));
      }
      if (top >= 6 || bump < 1) break;
      bump *= 0.75;
    }

    const frames = [];
    for (let s = 0; s <= steps; s++) {
      const t = s / steps;
      const p = point(t, bump);
      const scale = scaleAt(t);
      const swing = Math.sin(Math.PI * t);
      frames.push({
        offset: t,
        transform: `translate(${(p.x - x0).toFixed(1)}px, ${(p.y - y0).toFixed(1)}px) perspective(700px) rotateY(${(dir * 22 * swing).toFixed(2)}deg) rotate(${(dir * -9 * swing).toFixed(2)}deg) scale(${scale.toFixed(4)})`,
        opacity: t < 0.82 ? 1 : lerp(1, 0, (t - 0.82) / 0.18),
      });
    }
    const duration = Math.round(Math.min(1150, Math.max(760, 620 + distance * 0.42)));
    const flight = clone.animate(frames, { duration, easing: "linear", fill: "forwards" });

    // motes of light trailing the jacket
    const motes = [];
    [0.22, 0.34, 0.46, 0.58, 0.7].forEach((t, i) => {
      const p = point(t, bump);
      const mote = layer("tg-fly-mote", p);
      mote.style.setProperty("--mote", `${6 + (i % 2) * 3}px`);
      motes.push(mote);
      mote.animate(
        [
          { opacity: 0, transform: "translate(-50%, -50%) scale(0.3)" },
          { opacity: 0.9, transform: "translate(-50%, -50%) scale(1)", offset: 0.25 },
          { opacity: 0, transform: `translate(-50%, calc(-50% + ${8 + i * 2}px)) scale(0.2)` },
        ],
        { duration: 640, delay: t * duration, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "both" },
      ).finished.then(() => mote.remove(), () => mote.remove());
    });

    const cleanup = () => { clone.remove(); motes.forEach(m => m.remove()); };
    flight.finished.then(() => { cleanup(); if (target.isConnected) pulse(target); }, cleanup);
    setTimeout(cleanup, duration + 1400);
  } catch {
    /* decoration only — never let the flight break adding a book */
  }
}
