/* ============================================================
   Reading defaults (with a live typographic page) and Audio (narrator,
   speed, auto-advance). Both sync to the account; Reading also mirrors
   into localStorage "nw-reader" so this device picks it up at once.
   ============================================================ */
import React, { useState } from "react";

import { identityApi } from "./api.js";
import { Group, SectionHead, Slider, Switch, useRadioGroup } from "./AccountParts.jsx";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, SegmentedControl, Skeleton } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { motion, springs } from "../../motion/index.js";
import { VoicePicker } from "../narration/index.js";
import { useVoicesQuery } from "../narration/queries.js";

const FONTS = [
  { id: "serif", name: "Literata", kind: "Serif", family: "var(--font-read)" },
  { id: "sans", name: "Geist", kind: "Sans", family: "var(--font-ui)" },
];

/* Measures mirror the reader's column (reader.css .w-*). */
const WIDTHS = [
  { value: "narrow", label: "Narrow", ch: 55 },
  { value: "normal", label: "Normal", ch: 65 },
  { value: "wide", label: "Wide", ch: 80 },
  { value: "full", label: "Full", ch: null },
];

/* Tight / loose leading glyph for the line-height slider ends. */
function LinesGlyph({ gap }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      {[9 - gap, 9, 9 + gap].map((y, k) => <path key={k} d={`M3 ${y.toFixed(1)} H${k === 2 ? 11 : 15}`} />)}
    </svg>
  );
}

export function ReadingSection() {
  const { user, onUserUpdate } = useAuth();
  const { toast } = useToast();
  const synced = (user && user.prefs && user.prefs.reader) || {};
  const [font, setFont] = useState(synced.font || "serif");
  const [size, setSize] = useState(synced.size || 19);
  const [line, setLine] = useState(synced.line || 1.7);
  const [width, setWidth] = useState(synced.width || "normal");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const prefs = { ...synced, font, size, line, width };
      const u = await identityApi.updateMe({ prefs: { reader: prefs } });
      try { localStorage.setItem("nw-reader", JSON.stringify({ ...JSON.parse(localStorage.getItem("nw-reader") || "{}"), font, size, line, width })); } catch (e) { /* ignore */ }
      onUserUpdate && onUserUpdate(u);
      toast("Reading defaults saved.", { tone: "ok" });
    } catch (e) {
      toast(e.message || "Couldn't save.", { tone: "danger" });
    } finally { setSaving(false); }
  }

  const face = FONTS.find(f => f.id === font) || FONTS[0];
  const measure = WIDTHS.find(w => w.value === width) || WIDTHS[1];
  const fontRadio = useRadioGroup(FONTS.map(f => f.id), font, setFont);
  const pageStyle = {
    "--rp-font": face.family, "--rp-size": `${size}px`, "--rp-line": line,
    "--rp-measure": measure.ch ? `${measure.ch}ch` : "100%",
  };

  return (
    <section className="acct-section" aria-labelledby="acct-h-reading">
      <SectionHead id="acct-h-reading" icon="bookOpen" title="Reading"
                   lead="The page every book opens on. Adjust it here and watch the preview follow." />

      <Group i={1} className="acct-preview-card" title="Preview"
             aside={<span className="acct-spec">{face.name} · {size}px · {Number(line).toFixed(1)} · {measure.ch ? `${measure.ch} ch` : "full width"}</span>}>
        <div className="acct-sheet" style={pageStyle} aria-label="Preview of your reading defaults" role="img">
          <div className="acct-sheet-col" aria-hidden="true">
            <p className="acct-sheet-kicker">Chapter one</p>
            <p className="acct-sheet-title">Low Water</p>
            <p className="acct-sheet-p first">The sea had gone out so far that it was only a rumour — a thin line of silver at the edge of the world. She walked toward it with the letter in her pocket, and the wet sand kept every step she gave it.</p>
            <p className="acct-sheet-p">Somewhere behind her a bell rang once, though no one in the village would ever admit to ringing it.</p>
          </div>
        </div>
      </Group>

      <Group i={2} title="Type & measure">
        <div className="acct-fonts" role="radiogroup" aria-label="Font">
          {FONTS.map((f, i) => {
            const on = font === f.id;
            return (
              <button key={f.id} type="button" className={"acct-font" + (on ? " on" : "")} {...fontRadio(f.id, i)}
                      onClick={() => setFont(f.id)}>
                {on && <motion.span layoutId="acct-font-ring" className="acct-choice-ring" transition={springs.layout} aria-hidden="true" />}
                <span className="acct-font-aa" style={{ fontFamily: f.family }} aria-hidden="true">Aa</span>
                <span className="acct-font-text"><b>{f.kind}</b><small>{f.name}</small></span>
                <span className="acct-radio" aria-hidden="true"><Icon name="check" size={12} sw={2.6} /></span>
              </button>
            );
          })}
        </div>
        <div className="acct-sliders">
          <Slider id="acct-size" label="Text size" value={size} min={14} max={28} step={1} onChange={setSize}
                  display={`${size}px`} valueText={`${size} pixels`} minGlyph="A" maxGlyph="A" />
          <Slider id="acct-line" label="Line height" value={line} min={1.3} max={2.2} step={0.1}
                  onChange={(v) => setLine(Math.round(v * 10) / 10)}
                  display={Number(line).toFixed(1)} valueText={`${Number(line).toFixed(1)} times the text size`}
                  minGlyph={<LinesGlyph gap={3.2} />} maxGlyph={<LinesGlyph gap={5.6} />} />
        </div>
        <div className="acct-field-block">
          <span className="acct-field-label" id="acct-width-label">Column width</span>
          <SegmentedControl value={width} onChange={setWidth} ariaLabel="Column width"
                            options={WIDTHS.map(w => ({ value: w.value, label: w.label }))} />
        </div>
        <div className="acct-actions">
          <Button variant="primary" loading={saving} onClick={save}>Save defaults</Button>
          <span className="acct-hint">These sync across devices; the reader's Aa menu changes them too.</span>
        </div>
      </Group>
    </section>
  );
}

const voiceMeta = (v) => [v && v.language, v && v.gender, v && v.accent].filter(Boolean).join(" · ");
const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];

export function AudioSection() {
  const { user, onUserUpdate } = useAuth();
  const { toast } = useToast();
  const { data: voicesData, isLoading, isFetching, refetch } = useVoicesQuery();
  const tts = (user && user.prefs && user.prefs.tts) || {};
  const [voice, setVoice] = useState(tts.voice || null);
  const [speed, setSpeed] = useState(Number(tts.speed) || 1);
  const [autoplay, setAutoplay] = useState(tts.autoplay !== false);
  const [saving, setSaving] = useState(false);

  const voices = ((voicesData && voicesData.voices) || []).filter(v => v.ready);
  const preferred = voices.find(v => v.id === voice) || null;
  const fallback = voices.find(v => v.id === (voicesData && voicesData.default)) || null;
  const shown = preferred || fallback;
  const narratorHelp = preferred
    ? (voiceMeta(preferred) || "Ready to read")
    : voice ? "Your preferred voice is offline — the server default reads for now"
      : "No preference yet — the server default reads";

  async function save() {
    setSaving(true);
    try {
      const u = await identityApi.updateMe({ prefs: { tts: { voice, speed, autoplay } } });
      onUserUpdate && onUserUpdate(u);
      toast("Audio preferences saved.", { tone: "ok" });
    } catch (e) {
      toast(e.message || "Couldn't save.", { tone: "danger" });
    } finally { setSaving(false); }
  }

  let body;
  if (isLoading) {
    body = (
      <Group i={1} title="Narration" aria-busy="true">
        <span className="sr-only" role="status">Loading narrators…</span>
        {[0, 1, 2].map(k => <Skeleton key={k} height={52} style={{ borderRadius: 14 }} />)}
      </Group>
    );
  } else if (voices.length === 0) {
    body = (
      <Group i={1} className="acct-offline">
        <span className="acct-offline-orb" aria-hidden="true"><Icon name="headphones" size={24} /></span>
        <div className="grow">
          <h3 className="acct-group-title">Narrators are resting</h3>
          <p className="acct-group-hint">Narration voices are offline right now — preferences appear here when the narrator is available.</p>
        </div>
        <Button variant="ghost" icon="refresh" loading={isFetching} onClick={() => refetch()}>Check again</Button>
      </Group>
    );
  } else {
    body = (
      <Group i={1} title="Narration" hint="Used whenever Tideglass reads a chapter aloud.">
        <div className="acct-rows">
          <div className="acct-row acct-narrator">
            <span className="acct-narrator-orb" aria-hidden="true">
              {[0.45, 0.8, 1, 0.65, 0.35].map((h, k) => <i key={k} style={{ "--h": h, "--k": k }} />)}
            </span>
            <div className="acct-row-text grow">
              <span className="acct-row-label">Preferred narrator</span>
              <span className="acct-narrator-name">{shown ? (shown.name || shown.id) : "Server default"}</span>
              <span className="acct-row-help">{narratorHelp}</span>
            </div>
            <VoicePicker voices={voices} value={voice} onChange={setVoice}
                         defaultVoice={voicesData && voicesData.default} preferredVoice={voice} />
          </div>
          <div className="acct-row acct-row-wrap">
            <div className="acct-row-text">
              <span className="acct-row-label">Playback speed</span>
              <span className="acct-row-help">Currently {speed}×</span>
            </div>
            <SegmentedControl value={speed} onChange={setSpeed} ariaLabel="Playback speed" className="acct-speed"
                              options={SPEEDS.map(s => ({ value: s, label: `${s}×` }))} />
          </div>
          <div className="acct-row">
            <Switch checked={autoplay} onChange={setAutoplay}
                    hint="Keeps listening hands-free until you pause.">
              Auto-advance to the next chapter when narration ends
            </Switch>
          </div>
        </div>
        <div className="acct-actions">
          <Button variant="primary" loading={saving} onClick={save}>Save audio preferences</Button>
        </div>
      </Group>
    );
  }

  return (
    <section className="acct-section" aria-labelledby="acct-h-audio">
      <SectionHead id="acct-h-audio" icon="headphones" title="Audio"
                   lead="How chapters sound when Tideglass reads them to you." />
      {body}
    </section>
  );
}
