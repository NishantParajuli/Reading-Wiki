/* ============================================================
   Reading settings (Aa). A glass popover hung under its button on wider
   screens, a bottom sheet on phones. It renders at the reader root
   (useOverlayPortal) so the capsule's glass can neither trap its position
   nor keep its own glass from blurring the page, and it keeps the reading
   tone's tokens.
   Keyboard: opening moves focus to the title, Tab stays inside, Escape or
   × hand focus back to the Aa button. Tone and typeface are radio groups
   with one Tab stop each; arrow keys move and choose.
   ============================================================ */
import React, { useCallback, useEffect, useLayoutEffect, useRef } from "react";

import { Icon } from "../../components/Icon.jsx";
import { SegmentedControl } from "../../components/ui.jsx";
import { useOverlayPortal } from "../../components/overlay.jsx";
import { clamp } from "../../lib/utils.js";
import { READER_FONTS, READER_TONES, readerFontFamily } from "./ReaderParts.jsx";

const SHEET_QUERY = "(max-width: 640px)";
const TABBABLE = "button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex='-1'])";
const fillPct = (value, min, max) => `${((value - min) / (max - min)) * 100}%`;

function Switch({ checked, onChange, label }) {
  return (
    <label className="rs-switch">
      <input type="checkbox" role="switch" checked={checked} aria-checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className="rs-switch-track" aria-hidden="true"><span className="rs-switch-thumb" /></span>
      <span>{label}</span>
    </label>
  );
}

/* One Tab stop per group; arrows (and Home/End) move focus and choose. */
function useRovingRadios(values, value, onChange) {
  const refs = useRef([]);
  const selected = values.indexOf(value);
  const onKeyDown = (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    const from = refs.current.indexOf(document.activeElement);
    const at = from >= 0 ? from : Math.max(0, selected);
    const next = step != null ? (at + step + values.length) % values.length
      : e.key === "Home" ? 0 : e.key === "End" ? values.length - 1 : null;
    if (next == null) return;
    e.preventDefault();
    onChange(values[next]);
    refs.current[next]?.focus();
  };
  const radio = (i) => ({
    ref: (node) => { refs.current[i] = node; },
    type: "button", role: "radio", "aria-checked": i === selected,
    tabIndex: i === Math.max(0, selected) ? 0 : -1,
  });
  return { onKeyDown, radio };
}

/* Wide screens: hang the panel under the Aa button, right-aligned with the
   capsule and kept inside the viewport. Phones get the CSS bottom sheet. */
function useAnchoredPanel(panelRef, anchorRef) {
  useLayoutEffect(() => {
    const panel = panelRef.current;
    const anchor = anchorRef.current;
    if (!panel || !anchor) return undefined;
    const place = () => {
      if (window.matchMedia(SHEET_QUERY).matches) return;
      const a = anchor.getBoundingClientRect();
      const edge = (anchor.closest(".reader-capsule") || anchor).getBoundingClientRect().right;
      const width = panel.offsetWidth;
      const left = clamp(edge - width, 12, Math.max(12, document.documentElement.clientWidth - 12 - width));
      panel.style.setProperty("--rs-top", `${Math.round(a.bottom + 12)}px`);
      panel.style.setProperty("--rs-left", `${Math.round(left)}px`);
      panel.style.setProperty("--rs-origin", `${Math.round(a.left + a.width / 2 - left)}px -12px`);
    };
    place();
    // The bar may still be sliding back into view when the panel opens.
    const bar = anchor.closest(".reader-bar");
    window.addEventListener("resize", place);
    if (bar) bar.addEventListener("transitionend", place);
    return () => {
      window.removeEventListener("resize", place);
      if (bar) bar.removeEventListener("transitionend", place);
    };
  }, [panelRef, anchorRef]);
}

/* A soft fade at whichever edge still has settings beyond it. */
function useScrollFade(panelRef, bodyRef) {
  const update = useCallback(() => {
    const body = bodyRef.current, panel = panelRef.current;
    if (!body || !panel) return;
    const more = [];
    if (body.scrollTop > 2) more.push("start");
    if (body.scrollTop + body.clientHeight < body.scrollHeight - 2) more.push("end");
    panel.dataset.more = more.join(" ");
  }, [panelRef, bodyRef]);
  useLayoutEffect(update);
  useEffect(() => {
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [update]);
  return update;
}

export function ReaderSettings({ prefs, setPrefs, onClose, anchorRef }) {
  const portal = useOverlayPortal();
  const panelRef = useRef(null);
  const bodyRef = useRef(null);
  const titleRef = useRef(null);
  const set = (k, v) => setPrefs(p => ({ ...p, [k]: v }));
  const nudge = (d) => set("size", clamp(prefs.size + d, 14, 28));
  const tones = useRovingRadios(READER_TONES.map(t => t.value), prefs.tone, v => set("tone", v));
  const fonts = useRovingRadios(READER_FONTS.map(f => f.value), prefs.font, v => set("font", v));

  useAnchoredPanel(panelRef, anchorRef);
  const onBodyScroll = useScrollFade(panelRef, bodyRef);

  // Close and hand focus back to the Aa button.
  const dismiss = useCallback(() => {
    onClose();
    if (anchorRef && anchorRef.current) anchorRef.current.focus({ preventScroll: true });
  }, [onClose, anchorRef]);

  useEffect(() => { if (titleRef.current) titleRef.current.focus({ preventScroll: true }); }, []);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") dismiss(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [dismiss]);

  // Tab and Shift+Tab cycle through the visible controls.
  const keepFocusInside = (e) => {
    if (e.key !== "Tab" || !panelRef.current) return;
    const items = Array.from(panelRef.current.querySelectorAll(TABBABLE))
      .filter(el => el.tabIndex >= 0 && el.getClientRects().length);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === titleRef.current)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  return portal(
    <div ref={panelRef} className="reader-settings" role="dialog" aria-label="Reading settings"
         onClick={e => e.stopPropagation()} onKeyDown={keepFocusInside}>
      <div className="rs-head">
        <div>
          <p className="rs-eyebrow">Reading settings</p>
          <h2 ref={titleRef} className="rs-title" tabIndex={-1}>Make yourself comfortable</h2>
        </div>
        <button type="button" className="icon-btn plain" aria-label="Close reading settings" onClick={dismiss}><Icon name="x" size={17} /></button>
      </div>

      <div ref={bodyRef} className="rs-body" onScroll={onBodyScroll}>
        <div className={"rs-preview reader-tone-" + prefs.tone} style={{
          "--rs-font": readerFontFamily(prefs.font), "--rs-size": prefs.size + "px", "--rs-line": prefs.line,
        }}>
          <p>The tide pulled back slowly, and for the first time the glass beneath the water caught the morning light.</p>
        </div>

        <div className="rs-group">
          <span className="rs-label">Tone</span>
          <div className="rs-tones" role="radiogroup" aria-label="Reading tone" onKeyDown={tones.onKeyDown}>
            {READER_TONES.map((t, i) => (
              <button key={t.value} {...tones.radio(i)} className={"rs-tone" + (prefs.tone === t.value ? " on" : "")}
                      title={t.hint} onClick={() => set("tone", t.value)}>
                <span className={"rs-tone-swatch reader-tone-" + t.value} aria-hidden="true">Aa</span>
                <span className="rs-tone-label">{t.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="rs-group">
          <span className="rs-label">Typeface</span>
          <div className="rs-fonts" role="radiogroup" aria-label="Font" onKeyDown={fonts.onKeyDown}>
            {READER_FONTS.map((f, i) => (
              <button key={f.value} {...fonts.radio(i)} className={"rs-font" + (prefs.font === f.value ? " on" : "")}
                      title={f.hint} onClick={() => set("font", f.value)}>
                <span className="rs-font-sample" style={{ fontFamily: f.family }} aria-hidden="true">Ag</span>
                <span className="rs-font-label">{f.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="rs-group">
          <span className="rs-label">Size <span className="rs-value">{prefs.size}px</span></span>
          <div className="rs-slider-row">
            <button type="button" className="rs-step" aria-label="Smaller text" onClick={() => nudge(-1)} disabled={prefs.size <= 14}><span style={{ fontSize: 12 }}>A</span></button>
            <input type="range" className="slider" min={14} max={28} step={1} value={prefs.size}
                   style={{ "--fill": fillPct(prefs.size, 14, 28) }}
                   aria-label="Font size" onChange={e => set("size", Number(e.target.value))} />
            <button type="button" className="rs-step" aria-label="Larger text" onClick={() => nudge(1)} disabled={prefs.size >= 28}><span style={{ fontSize: 18 }}>A</span></button>
          </div>
        </div>
        <div className="rs-group">
          <span className="rs-label">Line height <span className="rs-value">{prefs.line.toFixed(1)}</span></span>
          <input type="range" className="slider" min={1.3} max={2.2} step={0.1} value={prefs.line}
                 style={{ "--fill": fillPct(prefs.line, 1.3, 2.2) }}
                 aria-label="Line height" onChange={e => set("line", Math.round(Number(e.target.value) * 10) / 10)} />
        </div>
        <div className="rs-group rs-width">
          <span className="rs-label">Width</span>
          <SegmentedControl value={prefs.width} onChange={v => set("width", v)} ariaLabel="Column width"
            options={[{ value: "narrow", label: "Narrow" }, { value: "normal", label: "Normal" }, { value: "wide", label: "Wide" }, { value: "full", label: "Full" }]} />
        </div>
        <div className="rs-group rs-toggles">
          <Switch checked={!!prefs.justify} onChange={v => set("justify", v)} label="Justify" />
          <Switch checked={!!prefs.indent} onChange={v => set("indent", v)} label="Indent paragraphs" />
        </div>
        <div className="rs-group">
          <span className="rs-label">Auto-scroll <span className="rs-value">{prefs.autoScroll ? `speed ${prefs.autoSpeed}` : "off"}</span></span>
          <div className="rs-autoscroll">
            <SegmentedControl fit value={prefs.autoScroll} onChange={v => set("autoScroll", v)} ariaLabel="Auto-scroll"
              options={[{ value: false, label: "Off" }, { value: true, label: "On" }]} />
            <input type="range" className="slider" min={1} max={10} step={1} value={prefs.autoSpeed}
                   style={{ "--fill": fillPct(prefs.autoSpeed, 1, 10) }}
                   aria-label="Auto-scroll speed" disabled={!prefs.autoScroll}
                   onChange={e => set("autoSpeed", Number(e.target.value))} />
          </div>
        </div>
      </div>
    </div>
  );
}
