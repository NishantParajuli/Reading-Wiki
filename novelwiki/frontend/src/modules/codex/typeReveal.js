/* Presentational "writing" reveal for answers and recaps.
   The full text is already in the DOM (and stays one accessible string); a
   CSS mask sweeps each line in turn, block after block, with a glint at the
   pen tip (see .cx-type-block in surfaces/codex.css). Nothing is split into
   per-word nodes. Skipped under reduced motion or without CSS support, and a
   click anywhere on the text finishes it at once. */
import { useLayoutEffect, useRef } from "react";

const BLOCKS = ":scope > p, :scope > h1, :scope > h2, :scope > h3, :scope > blockquote, :scope > ul > li, :scope > ol > li";
const VARS = ["--lines", "--type-dur", "--type-delay"];

function prefersReduced() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

function supported() {
  try {
    return typeof CSS !== "undefined" && CSS.supports("width", "round(down, 1px, 1px)")
      && (CSS.supports("mask-image", "linear-gradient(#000, #000)") || CSS.supports("-webkit-mask-image", "linear-gradient(#000, #000)"));
  } catch { return false; }
}

export function useTypeReveal(text, { delay = 280, perLineMin = 110, perLineMax = 340, budget = 2600, gap = 120 } = {}) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root || !text || prefersReduced() || !supported()) return undefined;
    const body = root.querySelector(".answer-body") || root;
    const blocks = Array.from(body.querySelectorAll(BLOCKS)).map((el) => {
      const cs = getComputedStyle(el);
      let lh = parseFloat(cs.lineHeight);
      if (!Number.isFinite(lh) || lh <= 0) lh = (parseFloat(cs.fontSize) || 16) * 1.6;
      // offsetHeight ignores the card's entrance transform.
      const lines = Math.max(1, Math.round(el.offsetHeight / lh) || 1);
      return { el, lines };
    });
    if (!blocks.length) return undefined;
    const total = blocks.reduce((sum, block) => sum + block.lines, 0);
    const perLine = Math.max(perLineMin, Math.min(perLineMax, budget / total));
    let at = delay;
    blocks.forEach(({ el, lines }) => {
      const duration = lines * perLine;
      el.style.setProperty("--lines", String(lines));
      el.style.setProperty("--type-dur", `${Math.round(duration)}ms`);
      el.style.setProperty("--type-delay", `${Math.round(at)}ms`);
      el.classList.add("cx-type-block");
      at += duration + gap;
    });
    root.classList.add("is-typing");

    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      root.classList.remove("is-typing");
      blocks.forEach(({ el }) => {
        el.classList.remove("cx-type-block");
        VARS.forEach(name => el.style.removeProperty(name));
      });
    };
    const timer = setTimeout(finish, at + 160);
    root.addEventListener("pointerdown", finish);
    return () => {
      clearTimeout(timer);
      root.removeEventListener("pointerdown", finish);
      finish();
    };
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps
  return ref;
}
