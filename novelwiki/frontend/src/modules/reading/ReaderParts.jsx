import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Illustration } from "../codex/index.js";
import { prepareIllustratedHtml } from "./illustrationPlacement.js";
import { useNavigate } from "react-router-dom";

import { identityApi } from "../identity/api.js";
import { narrationApi } from "../narration/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, SegmentedControl } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { VoicePicker, readTtsPrefs } from "../narration/index.js";
import { clamp, fmtChapter } from "../../lib/utils.js";
import { activeNarrationChunk } from "./narrationGuide.js";
import { pollNarrationJob } from "./narrationPolling.js";

const READER_DEFAULTS = {
  font: "serif", size: 19, line: 1.7, width: "normal", tone: "default",
  justify: false, indent: false, autoScroll: false, autoSpeed: 3,
};
export const AUTOSCROLL_PX_PER_SEC = (speed) => Math.max(1, speed) * 28;
const TTS_SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];

/* Reading tones: "default" follows the app theme; the rest are fixed rooms. */
export const READER_TONES = [
  { value: "default", label: "Theme", hint: "Follows the app" },
  { value: "paper", label: "Paper", hint: "Warm white page" },
  { value: "sepia", label: "Sepia", hint: "Old book" },
  { value: "dusk", label: "Dusk", hint: "Soft dark" },
  { value: "night", label: "Night", hint: "True black" },
];
export const READER_FONTS = [
  { value: "serif", label: "Literata", family: "var(--font-read)", hint: "Book serif" },
  { value: "classic", label: "Fraunces", family: "var(--font-display)", hint: "Old-style" },
  { value: "sans", label: "Geist", family: "var(--font-ui)", hint: "Modern sans" },
  { value: "legible", label: "Atkinson", family: "var(--font-legible)", hint: "High legibility" },
];
export const readerFontFamily = (font) => (READER_FONTS.find(f => f.value === font) || READER_FONTS[0]).family;

// Module-level intent flag so auto-advance keeps playing into the next chapter.
let __ttsContinue = false;

export function loadReaderPrefs(user) {
  let local = {};
  try { local = JSON.parse(localStorage.getItem("nw-reader") || "{}") || {}; }
  catch (e) { local = {}; }
  const synced = user && user.prefs && user.prefs.reader && typeof user.prefs.reader === "object"
    ? user.prefs.reader : {};
  const merged = { ...READER_DEFAULTS, ...local, ...synced };
  for (const [key, options] of Object.entries({
    tone: READER_TONES.map(t => t.value), font: READER_FONTS.map(f => f.value), width: ["narrow", "normal", "wide", "full"],
  })) {
    if (!options.includes(merged[key])) merged[key] = READER_DEFAULTS[key];
  }
  for (const [key, min, max] of [["size", 14, 28], ["line", 1.3, 2.2], ["autoSpeed", 1, 10]]) {
    const value = Number(merged[key]);
    merged[key] = merged[key] != null && Number.isFinite(value) ? clamp(value, min, max) : READER_DEFAULTS[key];
  }
  for (const key of ["justify", "indent", "autoScroll"]) merged[key] = merged[key] === true;
  return merged;
}

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

/* ---------- Settings (Aa) sheet ---------- */
export function ReaderSettings({ prefs, setPrefs, onClose }) {
  const set = (k, v) => setPrefs(p => ({ ...p, [k]: v }));
  const nudge = (d) => set("size", clamp(prefs.size + d, 14, 28));
  return (
    <div className="reader-settings" role="region" aria-label="Reading settings" onClick={e => e.stopPropagation()}>
      <div className="rs-head">
        <div>
          <p className="rs-eyebrow">Reading settings</p>
          <b>Make yourself comfortable</b>
        </div>
        <button className="icon-btn plain" aria-label="Close reading settings" onClick={onClose}><Icon name="x" size={17} /></button>
      </div>
      <div className={"rs-preview reader-tone-" + prefs.tone} style={{
        "--rs-font": readerFontFamily(prefs.font), "--rs-size": prefs.size + "px", "--rs-line": prefs.line,
      }}>
        <p>The tide pulled back slowly, and for the first time the glass beneath the water caught the morning light.</p>
      </div>

      <div className="rs-group">
        <span className="rs-label">Tone</span>
        <div className="rs-tones" role="radiogroup" aria-label="Reading tone">
          {READER_TONES.map(t => (
            <button key={t.value} type="button" role="radio" aria-checked={prefs.tone === t.value}
                    className={"rs-tone" + (prefs.tone === t.value ? " on" : "")} title={t.hint}
                    onClick={() => set("tone", t.value)}>
              <span className={"rs-tone-swatch reader-tone-" + t.value} aria-hidden="true">Aa</span>
              <span className="rs-tone-label">{t.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="rs-group">
        <span className="rs-label">Typeface</span>
        <div className="rs-fonts" role="radiogroup" aria-label="Font">
          {READER_FONTS.map(f => (
            <button key={f.value} type="button" role="radio" aria-checked={prefs.font === f.value}
                    className={"rs-font" + (prefs.font === f.value ? " on" : "")} title={f.hint}
                    onClick={() => set("font", f.value)}>
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
      <div className="rs-group">
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
  );
}

export { TranslationTools } from "./TranslationTools.jsx";

/* ---------- Audio player ---------- */
export function AudioPlayer({
  novelId, number, ch, user, onUserUpdate, openReader, onAudioChange, autoEngage,
  narrationChunks = [], onNarrationGuideChange,
}) {
  const [voices, setVoices] = useState(null);
  const [voice, setVoice] = useState(() => readTtsPrefs(user).voice);
  const [defaultVoice, setDefaultVoice] = useState(null);
  const [speed, setSpeed] = useState(() => readTtsPrefs(user).speed);
  const [src, setSrc] = useState(null);
  const [timingManifest, setTimingManifest] = useState(null);
  const [state, setState] = useState("idle");          // idle|checking|generating|ready|error|untranslated
  const [msg, setMsg] = useState(null);
  const [availableVoices, setAvailableVoices] = useState([]);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [regenerating, setRegenerating] = useState(false);
  const audioRef = useRef(null);
  const pollRef = useRef(null);
  const guideEngagedRef = useRef(false);
  const guideSnapshotRef = useRef("");
  const posKey = `nw-tts:${novelId}:${number}:${voice || "none"}`;

  const stopPoll = () => {
    if (pollRef.current) {
      pollRef.current();
      pollRef.current = null;
    }
  };
  const syncNarrationGuide = useCallback((audio, { engaged = guideEngagedRef.current, playing } = {}) => {
    if (!onNarrationGuideChange) return;
    const timed = engaged && timingManifest != null;
    const next = {
      activeIndex: timed && audio
        ? activeNarrationChunk(
          narrationChunks, audio.currentTime, timingManifest,
        )
        : null,
      engaged: timed,
      playing: timed && (
        playing == null ? !!(audio && !audio.paused && !audio.ended) : playing
      ),
    };
    const snapshot = `${next.activeIndex ?? "none"}:${next.engaged}:${next.playing}`;
    if (snapshot === guideSnapshotRef.current) return;
    guideSnapshotRef.current = snapshot;
    onNarrationGuideChange(next);
  }, [narrationChunks, onNarrationGuideChange, timingManifest]);

  useEffect(() => {
    let cancel = false;
    narrationApi.ttsVoices().then(r => {
      if (cancel) return;
      const list = (r.voices || []).filter(v => v.ready);
      setVoices(list);
      setDefaultVoice(r.default || null);
      const pref = readTtsPrefs(user).voice;
      const ids = new Set(list.map(v => v.id));
      setVoice(v => ids.has(v) ? v : ((pref && ids.has(pref)) ? pref : ((r.default && ids.has(r.default)) ? r.default : ((list[0] && list[0].id) || null))));
    }).catch(() => { if (!cancel) setVoices([]); });
    return () => { cancel = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    stopPoll();
    if (audioRef.current) audioRef.current.pause();
    guideEngagedRef.current = false;
    syncNarrationGuide(null, { engaged: false, playing: false });
    setSrc(null); setTimingManifest(null); setMsg(null); setAvailableVoices([]);
    setCur(0); setDur(0); setPlaying(false); setRegenerating(false);
    if (!voice) { setState("idle"); return; }
    let cancel = false;
    setState("checking");
    narrationApi.chapterAudioStatus(novelId, number, voice).then(r => {
      if (cancel) return;
      setAvailableVoices(r.available_voices || []);
      if (r.cached) {
        setTimingManifest(r.timing || null);
        setSrc(narrationApi.chapterAudioUrl(novelId, number, voice));
        setState("ready");
        if (r.job_id) watchJob(r.job_id, true, true);
      } else if (r.job_id) {
        watchJob(r.job_id, false);
      } else if (r.reason === "untranslated") {
        setState("untranslated");
        setMsg("Translate this chapter before narrating it.");
      } else {
        setState("idle");
      }
    }).catch(() => { if (!cancel) setState("idle"); });
    return () => { cancel = true; stopPoll(); };
  }, [novelId, number, voice]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (guideEngagedRef.current && audioRef.current) syncNarrationGuide(audioRef.current);
  }, [narrationChunks, syncNarrationGuide]);

  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = speed; }, [speed, src]);

  // Auto-advance continuity + explicit ?listen=1 entry.
  useEffect(() => {
    if (state === "ready" && src && (__ttsContinue || autoEngage) && audioRef.current) {
      const p = audioRef.current.play();
      if (p && p.catch) p.catch(() => {});
    }
  }, [state, src, autoEngage]);

  function persist(next) {
    if (!user) return;
    identityApi.updateMe({ prefs: { tts: { voice, speed, ...next } } })
      .then(u => onUserUpdate && onUserUpdate(u)).catch(() => {});
  }
  function pickVoice(v) { setVoice(v); persist({ voice: v }); }
  function pickSpeed(s) { setSpeed(s); if (audioRef.current) audioRef.current.playbackRate = s; persist({ speed: s }); }

  function loadReadyAudio(r, force) {
    setAvailableVoices(r.available_voices || []);
    if (r.cached) {
      setTimingManifest(r.timing || null);
      setSrc(narrationApi.chapterAudioUrl(novelId, number, voice) + (force ? `&t=${Date.now()}` : ""));
      setState("ready");
      onAudioChange && onAudioChange();
      return true;
    }
    if (r.reason === "untranslated") {
      setState("untranslated");
      setMsg("Translate this chapter before narrating it.");
      return false;
    }
    setState("idle");
    return false;
  }

  function watchJob(jobId, force, keepReady = false) {
    stopPoll();
    setMsg(null);
    setRegenerating(keepReady);
    if (!keepReady) setState("generating");
    pollRef.current = pollNarrationJob({
      jobId,
      loadJob: async (id) => {
        const j = await narrationApi.ttsJob(id);
        // Fetching the final cache record is part of the retryable poll. A brief
        // disconnect after the durable job finishes must not strand the player.
        if (j.status === "done") {
          j.readyAudio = await narrationApi.chapterAudioStatus(novelId, number, voice);
        }
        return j;
      },
      onProgress: () => setMsg(null),
      onRetry: () => setMsg("Connection interrupted. Retrying…"),
      onTerminal: async (j) => {
        pollRef.current = null;
        setRegenerating(false);
        if (j.status === "done") {
          const ok = loadReadyAudio(j.readyAudio, force);
          if (!ok) { setState("error"); setMsg("Narration finished, but no playable audio was produced."); }
        } else if (j.status === "failed") {
          if (!keepReady) setState("error");
          setMsg(j.error || "Narration failed.");
        } else if (j.status === "canceled") {
          if (!keepReady) setState("idle");
        }
      },
      onError: (e) => {
        pollRef.current = null;
        setRegenerating(false);
        if (!keepReady) setState("error");
        setMsg(e.message || "Narration status is unavailable.");
      },
    });
  }

  async function generate(force) {
    if (!voice) return;
    const keepReady = !!(force && state === "ready" && src);
    if (audioRef.current) audioRef.current.pause();
    guideEngagedRef.current = false;
    syncNarrationGuide(null, { engaged: false, playing: false });
    setMsg(null); stopPoll();
    setRegenerating(keepReady);
    if (!keepReady) setState("generating");
    try {
      const r = await narrationApi.generateChapterAudio(novelId, number, voice, force);
      if (r.status === "ready") {
        setRegenerating(false);
        setTimingManifest(r.timing || null);
        setSrc(narrationApi.chapterAudioUrl(novelId, number, voice) + (force ? `&t=${Date.now()}` : ""));
        setState("ready");
        onAudioChange && onAudioChange();
        return;
      }
      if (r.job_id) watchJob(r.job_id, force, keepReady);
    } catch (e) {
      // The POST may have reached the server even when its response did not reach
      // the browser. Reconcile through the reload-safe status endpoint before
      // presenting a failure.
      if (!e.status) {
        try {
          const status = await narrationApi.chapterAudioStatus(novelId, number, voice);
          if (status.job_id) {
            if (status.cached && !src) {
              setTimingManifest(status.timing || null);
              setSrc(narrationApi.chapterAudioUrl(novelId, number, voice));
              setState("ready");
            }
            watchJob(status.job_id, force || status.cached, !!status.cached);
            return;
          }
        } catch (statusError) {
          // Preserve the original mutation error when reconciliation is also offline.
        }
      }
      setRegenerating(false);
      if (keepReady) setState("ready");
      if (e.status === 409) { setState("untranslated"); setMsg("Translate this chapter before narrating it."); }
      else if (e.status === 429) {
        if (!keepReady) setState("error");
        setMsg(e.message || "Monthly narration quota reached.");
      } else {
        if (!keepReady) setState("error");
        setMsg(e.message || "Couldn't start narration.");
      }
    }
  }

  function togglePlay() {
    const a = audioRef.current; if (!a) return;
    if (a.paused) { const p = a.play(); if (p && p.catch) p.catch(() => {}); } else { a.pause(); }
  }
  function skip(delta) {
    const a = audioRef.current; if (!a) return;
    a.currentTime = clamp(a.currentTime + delta, 0, a.duration || 0);
    setCur(a.currentTime); syncNarrationGuide(a);
  }
  function seek(e) {
    const a = audioRef.current; const t = Number(e.target.value);
    setCur(t);
    if (a) { a.currentTime = t; syncNarrationGuide(a); }
  }
  function cycleSpeed() {
    const i = TTS_SPEEDS.indexOf(speed);
    pickSpeed(TTS_SPEEDS[(i + 1) % TTS_SPEEDS.length]);
  }
  const fmt = (s) => {
    if (!isFinite(s) || s < 0) s = 0;
    const m = Math.floor(s / 60), sec = Math.floor(s % 60);
    return `${m}:${String(sec).padStart(2, "0")}`;
  };

  if (voices == null || voices.length === 0) return null;

  const voiceMap = new Map((voices || []).map(v => [v.id, v]));
  const prefVoice = readTtsPrefs(user).voice;
  const availableOtherVoices = (availableVoices || []).filter(v => v && v !== voice);
  const pct = dur > 0 ? (cur / dur) * 100 : 0;

  const picker = (
    <VoicePicker voices={voices} value={voice} onChange={pickVoice}
                 defaultVoice={defaultVoice} preferredVoice={prefVoice} />
  );

  const ready = state === "ready" && src;
  return (
    <div className={"audio-dock" + (ready ? " is-ready" : "") + (playing ? " is-playing" : "")}
         role="region" aria-label="Narration" onClick={e => e.stopPropagation()}
         style={{ "--pct": pct + "%" }}>
      {ready ? (
        <>
          <audio
            ref={audioRef} src={src} preload="metadata" style={{ display: "none" }}
            onPlay={() => {
              __ttsContinue = true; guideEngagedRef.current = true; setPlaying(true);
              syncNarrationGuide(audioRef.current, { engaged: true, playing: true });
            }}
            onPause={() => {
              __ttsContinue = false; setPlaying(false);
              const a = audioRef.current;
              if (!a || a.ended) return;
              syncNarrationGuide(a, { playing: false });
            }}
            onDurationChange={() => setDur(audioRef.current ? audioRef.current.duration || 0 : 0)}
            onLoadedMetadata={() => {
              const a = audioRef.current; if (!a) return;
              a.playbackRate = speed; setDur(a.duration || 0);
              const saved = parseFloat(localStorage.getItem(posKey) || "0");
              if (saved > 1 && saved < (a.duration || 1e9) - 2) { a.currentTime = saved; setCur(saved); }
            }}
            onTimeUpdate={() => {
              const a = audioRef.current; if (!a) return;
              setCur(a.currentTime);
              syncNarrationGuide(a);
              if (Math.floor(a.currentTime) % 5 === 0) localStorage.setItem(posKey, String(a.currentTime));
            }}
            onEnded={() => {
              localStorage.removeItem(posKey); guideEngagedRef.current = false; setPlaying(false);
              syncNarrationGuide(null, { engaged: false, playing: false });
              if (readTtsPrefs(user).autoplay && ch && ch.next != null) openReader(ch.next);
            }}
          />
          <div className="ad-transport">
            <button className="ad-skip" aria-label="Back 15 seconds" onClick={() => skip(-15)}>
              <Icon name="rotateCcw" size={19} /><span className="ad-skip-n" aria-hidden="true">15</span>
            </button>
            <button className={"ad-play" + (playing ? " is-playing" : "")} onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
              <span className="ad-play-ring" aria-hidden="true" />
              <Icon name={playing ? "pause" : "play"} size={18} />
            </button>
            <button className="ad-skip ad-skip-fwd" aria-label="Forward 15 seconds" onClick={() => skip(15)}>
              <Icon name="rotateCcw" size={19} /><span className="ad-skip-n" aria-hidden="true">15</span>
            </button>
          </div>
          <div className="ad-track">
            <span className="ad-time">{fmt(cur)}</span>
            <span className="ad-seek-wrap">
              <span className="ad-wave" aria-hidden="true" style={{ WebkitMaskImage: WAVE_MASK, maskImage: WAVE_MASK }} />
              <input type="range" className="ad-seek" min={0} max={dur || 0} step={0.1} value={Math.min(cur, dur || 0)}
                     onChange={seek} aria-label="Seek" />
            </span>
            <span className="ad-time">{fmt(dur)}</span>
          </div>
          <div className="ad-tools">
            <button className="ad-speed" onClick={cycleSpeed} aria-label="Playback speed">{speed}×</button>
            {picker}
            {regenerating ? (
              <span className="ab-status"><Icon name="refresh" size={14} className="spin" /> Updating…</span>
            ) : (
              <button className="icon-btn plain ad-regen" title="Regenerate this narration"
                      aria-label="Regenerate narration" onClick={() => generate(true)}>
                <Icon name="refresh" size={15} />
              </button>
            )}
          </div>
          {msg && <span className="ab-msg" role="status">{msg}</span>}
        </>
      ) : state === "generating" || state === "checking" ? (
        <div className="ad-idle">
          <span className="ad-orb is-busy" aria-hidden="true"><Icon name="headphones" size={16} /></span>
          <span className="ab-status">{state === "generating" ? "Narrating this chapter…" : "Checking narration…"}</span>
          {picker}
        </div>
      ) : (
        <div className="ad-idle">
          <span className="ad-orb" aria-hidden="true"><Icon name="headphones" size={16} /></span>
          {picker}
          <Button variant="secondary" size="sm" icon="play" onClick={() => generate(false)}
                  disabled={state === "untranslated"}>
            Narrate chapter
          </Button>
          {availableOtherVoices.length > 0 && (
            <span className="ab-alt">
              Available in{" "}
              {availableOtherVoices.map((vid, i) => (
                <React.Fragment key={vid}>
                  {i > 0 ? ", " : null}
                  <button className="ab-alt-btn" onClick={() => pickVoice(vid)}>
                    {(voiceMap.get(vid) && voiceMap.get(vid).name) || vid}
                  </button>
                </React.Fragment>
              ))}
            </span>
          )}
          {msg && <span className="ab-msg" role="status">{msg}</span>}
        </div>
      )}
    </div>
  );
}

/* A still, hand-tuned waveform silhouette under the seek bar (decorative). */
const WAVE_BARS = [0.35, 0.55, 0.4, 0.7, 0.5, 0.85, 0.6, 0.45, 0.75, 0.95, 0.65, 0.5, 0.8, 0.55, 0.4, 0.7, 0.9, 0.6, 0.45, 0.65, 0.8, 0.5, 0.35, 0.6, 0.75, 0.55, 0.85, 0.45, 0.6, 0.4, 0.7, 0.5, 0.65, 0.9, 0.55, 0.4, 0.6, 0.75, 0.5, 0.35];
/* The bars are a mask over a progress gradient, so played audio lights up. */
const WAVE_MASK = (() => {
  const width = WAVE_BARS.length * 6;
  const rects = WAVE_BARS.map((h, i) => {
    const height = (h * 34).toFixed(1);
    return `<rect x='${i * 6 + 1.3}' y='${((40 - h * 34) / 2).toFixed(1)}' width='3.4' height='${height}' rx='1.7'/>`;
  }).join("");
  return `url("data:image/svg+xml,${encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 ${width} 40' preserveAspectRatio='none'>${rects}</svg>`)}")`;
})();

/* ---------- End of chapter: the tide turns ---------- */
export function EndOfChapterCard({ ch, novelId, onNext, onPrev }) {
  const navigate = useNavigate();
  const ref = useRef(null);
  const [arrived, setArrived] = useState(false);
  const nextIsRaw = ch.next != null && ch.next_is_raw;
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") { setArrived(true); return undefined; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some(e => e.isIntersecting)) { setArrived(true); io.disconnect(); }
    }, { threshold: 0.35 });
    io.observe(node);
    return () => io.disconnect();
  }, []);
  return (
    <section ref={ref} className={"eoc" + (arrived ? " is-arrived" : "")} aria-label="End of chapter">
      <svg className="eoc-wave" viewBox="0 0 600 40" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0 20 C 50 4, 100 4, 150 20 S 250 36, 300 20 S 400 4, 450 20 S 550 36, 600 20" />
      </svg>
      <div className="eoc-seal" aria-hidden="true">
        <span className="eoc-burst">{Array.from({ length: 12 }, (_, i) => <i key={i} style={{ "--a": `${i * 30}deg`, "--d": `${(i % 3) * 40}ms` }} />)}</span>
        <svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="21" /><path d="M15 24.5l6 6 12-13" /></svg>
      </div>
      <p className="eoc-done">Chapter {fmtChapter(ch.number)} complete</p>
      {ch.next != null ? (
        <>
          <p className="eoc-next-label">Up next</p>
          <h3 className="eoc-next-title">
            Chapter {fmtChapter(ch.next)}
            {ch.next_title ? <><span className="eoc-dash"> — </span><em>{ch.next_title}</em></> : null}
          </h3>
          <div className="eoc-actions">
            <Button variant="primary" size="lg" full iconRight="arrowRight" onClick={onNext}>
              {nextIsRaw ? "Translate & continue" : "Next chapter"}
            </Button>
          </div>
        </>
      ) : (
        <>
          <h3 className="eoc-next-title">You're all caught up</h3>
          <p className="eoc-caught">That's the last chapter for now. New ones will wash up here.</p>
        </>
      )}
      <div className="eoc-links">
        {ch.prev != null && <button className="linkish" onClick={onPrev}><Icon name="arrowLeft" size={13} /> Previous</button>}
        <button className="linkish" onClick={() => navigate(`/n/${novelId}/chapters`)}>Contents</button>
        <button className="linkish" onClick={() => navigate(`/n/${novelId}`)}>About this book</button>
      </div>
    </section>
  );
}

/* ---------- Reader ---------- */
const NO_ILLUSTRATIONS = [];
export function RichContent({ html, illustrations = NO_ILLUSTRATIONS }) {
  const proseRef = useRef(null);
  const prepared = useMemo(() => prepareIllustratedHtml(html, illustrations), [html, illustrations]);
  const [portals, setPortals] = useState([]);
  useLayoutEffect(() => {
    setPortals(prepared.targets.flatMap(({ index, scene }) => {
      const node = proseRef.current?.querySelector(`[data-illustration-slot="${index}"]`);
      return node ? [{ node, scene }] : [];
    }));
  }, [prepared]);
  const [lightbox, setLightbox] = useState(null);
  const onClick = (e) => {
    const img = e.target.closest("img");
    if (img && img.src && !img.closest(".chapter-art")) { e.stopPropagation(); setLightbox(img.src); }
  };
  return (
    <>
      <div ref={proseRef} className="reader-text reader-rich" onClick={onClick} dangerouslySetInnerHTML={{ __html: prepared.html }} />
      {portals.map(({ node, scene }) => createPortal(<Illustration item={scene} inline />, node, scene.id))}
      {lightbox && (
        <div className="lightbox-scrim" onClick={(e) => { e.stopPropagation(); setLightbox(null); }}>
          <img src={lightbox} alt="" />
        </div>
      )}
    </>
  );
}
