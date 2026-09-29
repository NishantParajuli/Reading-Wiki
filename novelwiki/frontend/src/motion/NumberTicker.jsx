/* Counts up to `value` once it scrolls into view (tabular numerals, so the
   layout never jitters). Non-numeric values render as-is. */
import React, { useEffect, useRef, useState } from "react";
import { animate, useInView, useReducedMotion } from "motion/react";

export function NumberTicker({ value, duration = 1.1, format, className = "" }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -10% 0px" });
  const reduced = useReducedMotion();
  const numeric = typeof value === "number" && Number.isFinite(value);
  const [shown, setShown] = useState(numeric && !reduced ? 0 : value);

  useEffect(() => {
    if (!numeric) { setShown(value); return undefined; }
    if (reduced || !inView) { if (reduced) setShown(value); return undefined; }
    const controls = animate(0, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setShown(Math.round(v)),
    });
    return () => controls.stop();
  }, [value, numeric, inView, reduced, duration]);

  const text = numeric ? (format ? format(shown) : Number(shown).toLocaleString()) : value;
  return <span ref={ref} className={["tabular", className].filter(Boolean).join(" ")}>{text}</span>;
}
