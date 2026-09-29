/* ============================================================
   Pointer effects, installed once for the whole document.

   Markup opts in with data attributes — no per-component listeners:
     data-tilt="8"      3D tilt toward the pointer (max degrees); exposes
                        --rx/--ry and glare coordinates --gx/--gy, and sets
                        [data-tilting] while active.
     data-spotlight     exposes --mx/--my (px) for cursor-following light and
                        sets [data-lit] while hovered.
     .btn / .icon-btn / [data-ripple]
                        a tide ripple expands from the press point.
   Fine pointers only for tilt/spotlight; everything is inert under
   prefers-reduced-motion. Work is coalesced to one write per frame.
   ============================================================ */

export function installPointerFX() {
  if (typeof window === "undefined" || window.__tgPointerFX) return () => {};
  window.__tgPointerFX = true;
  const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let tiltEl = null;
  let spotEl = null;
  let raf = 0;
  let last = null;

  const resetTilt = (el) => {
    delete el.dataset.tilting;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };

  const frame = () => {
    raf = 0;
    const e = last;
    if (!e) return;
    const target = e.target instanceof Element ? e.target : null;
    const allow = fine.matches && !reduced.matches;

    const nextTilt = allow && target ? target.closest("[data-tilt]") : null;
    if (nextTilt !== tiltEl) { if (tiltEl) resetTilt(tiltEl); tiltEl = nextTilt; }
    if (tiltEl) {
      const r = tiltEl.getBoundingClientRect();
      if (r.width && r.height) {
        const px = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
        const py = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
        const max = Number(tiltEl.dataset.tilt) || 8;
        tiltEl.style.setProperty("--rx", `${((0.5 - py) * max * 2).toFixed(2)}deg`);
        tiltEl.style.setProperty("--ry", `${((px - 0.5) * max * 2).toFixed(2)}deg`);
        tiltEl.style.setProperty("--gx", `${(px * 100).toFixed(1)}%`);
        tiltEl.style.setProperty("--gy", `${(py * 100).toFixed(1)}%`);
        tiltEl.dataset.tilting = "";
      }
    }

    const nextSpot = allow && target ? target.closest("[data-spotlight]") : null;
    if (nextSpot !== spotEl) { if (spotEl) delete spotEl.dataset.lit; spotEl = nextSpot; }
    if (spotEl) {
      const r = spotEl.getBoundingClientRect();
      spotEl.style.setProperty("--mx", `${(e.clientX - r.left).toFixed(0)}px`);
      spotEl.style.setProperty("--my", `${(e.clientY - r.top).toFixed(0)}px`);
      spotEl.dataset.lit = "";
    }
  };

  const onMove = (e) => {
    if (e.pointerType && e.pointerType !== "mouse" && e.pointerType !== "pen") return;
    last = e;
    if (!raf) raf = requestAnimationFrame(frame);
  };
  const onLeave = (e) => {
    if (e.relatedTarget) return;
    last = null;
    if (tiltEl) { resetTilt(tiltEl); tiltEl = null; }
    if (spotEl) { delete spotEl.dataset.lit; spotEl = null; }
  };

  const onDown = (e) => {
    if (reduced.matches || e.button > 0) return;
    const host = e.target instanceof Element ? e.target.closest(".btn, .icon-btn, [data-ripple]") : null;
    if (!host || host.disabled || host.getAttribute("aria-disabled") === "true") return;
    const r = host.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2.2;
    const ink = document.createElement("span");
    ink.className = "tide-ripple";
    ink.setAttribute("aria-hidden", "true");
    ink.style.width = ink.style.height = `${size}px`;
    ink.style.left = `${e.clientX - r.left - size / 2}px`;
    ink.style.top = `${e.clientY - r.top - size / 2}px`;
    host.appendChild(ink);
    ink.addEventListener("animationend", () => ink.remove(), { once: true });
    setTimeout(() => ink.remove(), 1200);
  };

  document.addEventListener("pointermove", onMove, { passive: true });
  document.addEventListener("pointerout", onLeave, { passive: true });
  document.addEventListener("pointerdown", onDown, { passive: true });
  return () => {
    document.removeEventListener("pointermove", onMove);
    document.removeEventListener("pointerout", onLeave);
    document.removeEventListener("pointerdown", onDown);
    window.__tgPointerFX = false;
  };
}
