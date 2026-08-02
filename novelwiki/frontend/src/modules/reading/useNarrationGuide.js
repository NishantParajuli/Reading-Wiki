import { useEffect, useMemo, useRef, useState } from "react";

import {
  buildPlainNarrationGuide, buildRichNarrationGuide,
} from "./narrationGuide.js";

const INACTIVE_GUIDE = { activeIndex: null, engaged: false, playing: false };

export function useNarrationGuide({ ch, novelId, number, chrome }) {
  const readerRef = useRef(null);
  const [narrationGuide, setNarrationGuide] = useState(INACTIVE_GUIDE);
  const preparedNarration = useMemo(() => {
    if (!ch) return { kind: "plain", chunks: [], paragraphs: [] };
    return ch.rich_html
      ? buildRichNarrationGuide(ch.rich_html, ch.content || "")
      : buildPlainNarrationGuide(ch.content || "");
  }, [ch && ch.content, ch && ch.rich_html]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setNarrationGuide(INACTIVE_GUIDE);
  }, [novelId, number]);

  // Keep only the estimated sentence group at the timed paragraph playhead highlighted.
  // Scrolling is limited to chunk transitions and only runs during actual playback.
  useEffect(() => {
    const root = readerRef.current;
    if (!root) return;
    root.querySelectorAll("[data-narration-active]").forEach((node) => {
      node.removeAttribute("data-narration-active");
    });
    if (narrationGuide.activeIndex == null) return;

    const nodes = Array.from(
      root.querySelectorAll(`[data-narration-chunk="${narrationGuide.activeIndex}"]`),
    );
    nodes.forEach(node => node.setAttribute("data-narration-active", "true"));
    if (!narrationGuide.playing || !nodes.length) return;

    const raf = requestAnimationFrame(() => {
      const rects = nodes.map(node => node.getBoundingClientRect());
      const top = Math.min(...rects.map(rect => rect.top));
      const bottom = Math.max(...rects.map(rect => rect.bottom));
      const stickyBottoms = chrome
        ? Array.from(root.querySelectorAll(".reader-bar:not(.hidden), .audio-bar"))
          .map(node => node.getBoundingClientRect().bottom)
        : [];
      const footer = chrome ? root.querySelector(".reader-foot:not(.hidden)") : null;
      const topInset = Math.max(24, ...stickyBottoms.map(value => value + 16));
      const bottomInset = footer
        ? Math.max(28, window.innerHeight - footer.getBoundingClientRect().top + 16)
        : 28;
      const safeBottom = window.innerHeight - bottomInset;
      if (top >= topInset && bottom <= safeBottom) return;

      const center = (top + bottom) / 2;
      const targetTop = Math.max(0, window.scrollY + center - (window.innerHeight * 0.46));
      const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: targetTop, behavior: reduceMotion ? "auto" : "smooth" });
    });
    return () => cancelAnimationFrame(raf);
  }, [narrationGuide.activeIndex, narrationGuide.playing, chrome]);

  return {
    readerRef,
    narrationGuide,
    preparedNarration,
    setNarrationGuide,
  };
}
