/* Hand-rolled window renderer for long flat lists (1,400-chapter TOCs).
   Fixed row height; renders only the visible slice + overscan. Uses the
   window as the scroll container so it composes with the normal page. */
import React, { useEffect, useRef, useState } from "react";

export function VirtualList({ items, rowHeight, renderRow, overscan = 12, scrollToIndex }) {
  const wrapRef = useRef(null);
  const [range, setRange] = useState({ start: 0, end: 40 });

  useEffect(() => {
    const update = () => {
      const el = wrapRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const viewTop = -rect.top;
      const viewH = window.innerHeight;
      const start = Math.max(0, Math.floor(viewTop / rowHeight) - overscan);
      const end = Math.min(items.length, Math.ceil((viewTop + viewH) / rowHeight) + overscan);
      setRange(r => (r.start === start && r.end === end) ? r : { start, end });
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => { window.removeEventListener("scroll", update); window.removeEventListener("resize", update); };
  }, [items.length, rowHeight, overscan]);

  // Scroll the requested row into view once (e.g. the continue-position chapter).
  const didScroll = useRef(null);
  useEffect(() => {
    if (scrollToIndex == null || scrollToIndex < 0) return;
    if (didScroll.current === scrollToIndex) return;
    didScroll.current = scrollToIndex;
    const el = wrapRef.current;
    if (!el) return;
    const y = el.getBoundingClientRect().top + window.scrollY + scrollToIndex * rowHeight - window.innerHeight / 3;
    window.scrollTo({ top: Math.max(0, y) });
  }, [scrollToIndex, rowHeight]);

  const slice = items.slice(range.start, range.end);
  return (
    <div ref={wrapRef} style={{ position: "relative", height: items.length * rowHeight }}>
      <div style={{ position: "absolute", top: range.start * rowHeight, left: 0, right: 0 }}>
        {slice.map((item, i) => renderRow(item, range.start + i))}
      </div>
    </div>
  );
}
