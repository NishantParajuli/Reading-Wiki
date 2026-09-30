import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Illustration } from "../codex/index.js";
import { prepareIllustratedHtml } from "./illustrationPlacement.js";
import { useNavigate } from "react-router-dom";

import { identityApi } from "../identity/api.js";
import { narrationApi } from "../narration/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button } from "../../components/ui.jsx";
import { useOverlayPortal } from "../../components/overlay.jsx";
import { useFocusTrap } from "../../lib/hooks.js";
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
              <Icon name="rotateCcw" size={24} sw={1.5} /><span className="ad-skip-n" aria-hidden="true">15</span>
            </button>
            <button className={"ad-play" + (playing ? " is-playing" : "")} onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
              <span className="ad-play-ring" aria-hidden="true" />
              <Icon name={playing ? "pause" : "play"} size={18} />
            </button>
            <button className="ad-skip ad-skip-fwd" aria-label="Forward 15 seconds" onClick={() => skip(15)}>
              <Icon name="rotateCcw" size={24} sw={1.5} /><span className="ad-skip-n" aria-hidden="true">15</span>
            </button>
          </div>
          <div className="ad-track">
            <span className="ad-time">{fmt(cur)}</span>
            <span className="ad-seek-wrap">
              <TideLine />
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

/* The seek track's tide line: an even swell, deliberately not a waveform —
   it carries no audio data. Two swells drift while narration plays and settle
   flat when it pauses; the stretch already heard is lit (--pct). */
const swell = (period, lift) => {
  let d = "M0 8";
  for (let x = 0; x < 1600; x += period) d += ` Q${x + period / 4} ${8 - lift} ${x + period / 2} 8 T${x + period} 8`;
  return d;
};
const SWELLS = [swell(60, 4), swell(30, 6)];
function TideLine() {
  const layer = (heard) => (
    <span className={"ad-tide-layer" + (heard ? " is-heard" : "")}>
      {SWELLS.map((d, i) => <svg key={i} className={`ad-swell ad-swell-${i}`} height="16"><path d={d} /></svg>)}
    </span>
  );
  return <span className="ad-tide" aria-hidden="true">{layer(false)}{layer(true)}</span>;
}

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
          <h2 className="eoc-next-title">
            Chapter {fmtChapter(ch.next)}
            {ch.next_title ? <><span className="eoc-dash"> — </span><em>{ch.next_title}</em></> : null}
          </h2>
          <div className="eoc-actions">
            <Button variant="primary" size="lg" full iconRight="arrowRight" onClick={onNext}>
              {nextIsRaw ? "Translate & continue" : "Next chapter"}
            </Button>
          </div>
        </>
      ) : (
        <>
          <h2 className="eoc-next-title">You're all caught up</h2>
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

/* The enlarged picture: a modal that holds focus, closes on Escape, its close
   button or a tap, and hands focus back to the picture it came from. */
function Lightbox({ image, onClose }) {
  const trapRef = useFocusTrap(true);
  const portal = useOverlayPortal();
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return portal(
    <div ref={trapRef} className="lightbox-scrim" role="dialog" aria-modal="true"
         aria-label={image.alt ? `Image: ${image.alt}` : "Image"}
         onClick={(e) => { e.stopPropagation(); onClose(); }}>
      <img src={image.src} alt={image.alt} />
      <button type="button" className="icon-btn lightbox-close" aria-label="Close image"
              onClick={(e) => { e.stopPropagation(); onClose(); }}>
        <Icon name="x" size={18} />
      </button>
    </div>
  );
}

/* ---------- Reader ---------- */
const NO_ILLUSTRATIONS = [];
const zoomable = (node) => node && node.tagName === "IMG" && node.src && !node.closest(".chapter-art");
export function RichContent({ html, illustrations = NO_ILLUSTRATIONS }) {
  const proseRef = useRef(null);
  const prepared = useMemo(() => prepareIllustratedHtml(html, illustrations), [html, illustrations]);
  const [portals, setPortals] = useState([]);
  useLayoutEffect(() => {
    setPortals(prepared.targets.flatMap(({ index, scene }) => {
      const node = proseRef.current?.querySelector(`[data-illustration-slot="${index}"]`);
      return node ? [{ node, scene }] : [];
    }));
    // Pictures open larger by keyboard too (unless a link already owns them).
    proseRef.current?.querySelectorAll("img").forEach(img => {
      if (!zoomable(img) || img.closest("a")) return;
      img.tabIndex = 0;
      img.setAttribute("role", "button");
      img.setAttribute("aria-label", img.alt ? `Enlarge image: ${img.alt}` : "Enlarge image");
    });
  }, [prepared]);
  const [lightbox, setLightbox] = useState(null);
  const closeLightbox = useCallback(() => setLightbox(null), []);
  const open = (e) => {
    const img = e.target.closest("img");
    if (!zoomable(img)) return;
    e.stopPropagation();
    setLightbox({ src: img.currentSrc || img.src, alt: img.getAttribute("alt") || "" });
  };
  const onKeyDown = (e) => {
    if ((e.key === "Enter" || e.key === " ") && zoomable(e.target)) { e.preventDefault(); open(e); }
  };
  return (
    <>
      <div ref={proseRef} className="reader-text reader-rich" onClick={open} onKeyDown={onKeyDown}
           dangerouslySetInnerHTML={{ __html: prepared.html }} />
      {portals.map(({ node, scene }) => createPortal(<Illustration item={scene} inline />, node, scene.id))}
      {lightbox && <Lightbox image={lightbox} onClose={closeLightbox} />}
    </>
  );
}
