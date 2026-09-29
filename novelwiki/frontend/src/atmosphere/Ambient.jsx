/* ============================================================
   Ambient — the room behind the pages, back to front:
     1. TideCanvas   living water in the atmosphere's hues
     2. Aura         the focused book's jacket, enormous and out of focus
                     (a tiny image scaled up: the upscale is the blur, so it
                     costs almost nothing and works for any cover origin)
     3. Grain        film grain for a tactile, printed feel
   Two aura layers crossfade when the book changes.
   ============================================================ */
import React, { useEffect, useState } from "react";
import { TideCanvas } from "./TideCanvas.jsx";
import { useAtmosphere } from "./store.js";

function useAmbientMode() {
  const read = () => { try { return localStorage.getItem("nw-ambient") || "living"; } catch { return "living"; } };
  const [mode, setMode] = useState(read);
  useEffect(() => {
    const onChange = () => setMode(read());
    window.addEventListener("tg-ambient-change", onChange);
    return () => window.removeEventListener("tg-ambient-change", onChange);
  }, []);
  return mode;
}

let auraId = 0;
function Aura() {
  const { cover } = useAtmosphere();
  const [layers, setLayers] = useState([]);
  useEffect(() => {
    setLayers((prev) => {
      const current = prev.find((l) => !l.leaving);
      if ((current ? current.src : null) === (cover || null)) return prev;
      const retired = prev.map((l) => ({ ...l, leaving: true }));
      return cover ? [...retired, { src: cover, id: ++auraId }] : retired;
    });
  }, [cover]);
  useEffect(() => {
    if (!layers.some((l) => l.leaving)) return undefined;
    const t = setTimeout(() => setLayers((prev) => prev.filter((l) => !l.leaving)), 1600);
    return () => clearTimeout(t);
  }, [layers]);
  return (
    <div className="ambient-aura" aria-hidden="true">
      {layers.map((layer) => <AuraLayer key={layer.id} src={layer.src} leaving={layer.leaving} />)}
    </div>
  );
}

/* The jacket is painted into a 24×36 canvas (pixels are never read, so any
   cover origin works) and scaled up by the compositor: a free, huge blur.
   Colour grading happens in the draw — a CSS filter on an element this large
   gets clipped by the compositor and shows hard edges. */
function useThemeName() {
  const read = () => document.documentElement.getAttribute("data-theme") || "dark";
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}

function AuraLayer({ src, leaving }) {
  const canvasRef = React.useRef(null);
  const [painted, setPainted] = useState(false);
  const theme = useThemeName();
  useEffect(() => {
    let cancelled = false;
    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      if (cancelled || !canvasRef.current) return;
      const ctx = canvasRef.current.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, 24, 36);
      try {
        ctx.filter = theme === "light"
          ? "blur(1.2px) saturate(1.7) brightness(1.35) contrast(0.8)"
          : "blur(1.2px) saturate(1.8)";
      } catch { /* older engines draw ungraded */ }
      ctx.drawImage(img, -2, -2, 28, 40);
      setPainted(true);
    };
    img.src = src;
    return () => { cancelled = true; };
  }, [src, theme]);
  return (
    <div className={"ambient-aura-layer" + (leaving ? " is-leaving" : "") + (painted ? " is-painted" : "")}>
      <canvas ref={canvasRef} width={24} height={36} />
    </div>
  );
}

export function Ambient() {
  const mode = useAmbientMode();
  return (
    <div className="ambient" data-mode={mode} aria-hidden="true">
      {mode !== "off" ? <TideCanvas /> : <div className="ambient-fallback" />}
      <Aura />
      <div className="ambient-grain" />
    </div>
  );
}

/** Persist the ambient preference ("living" | "still" | "off") and notify. */
export function setAmbientMode(mode) {
  try { localStorage.setItem("nw-ambient", mode); } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event("tg-ambient-change"));
}
