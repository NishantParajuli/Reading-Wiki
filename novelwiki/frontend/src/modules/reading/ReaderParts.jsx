import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { identityApi } from "../identity/api.js";
import { narrationApi } from "../narration/api.js";
import { readingApi } from "./api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, Loading, SegmentedControl } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { DiffView } from "../../lib/diff.jsx";
import { VoicePicker, readTtsPrefs } from "../../features/narrate.jsx";
import { clamp, fmtChapter } from "../../lib/utils.js";

const READER_DEFAULTS = {
  font: "serif", size: 19, line: 1.7, width: "normal", tone: "default",
  justify: false, indent: false, autoScroll: false, autoSpeed: 3,
};
export const AUTOSCROLL_PX_PER_SEC = (speed) => Math.max(1, speed) * 28;
const TTS_SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];

// Module-level intent flag so auto-advance keeps playing into the next chapter.
let __ttsContinue = false;

export function loadReaderPrefs(user) {
  let local = {};
  try { local = JSON.parse(localStorage.getItem("nw-reader") || "{}") || {}; }
  catch (e) { local = {}; }
  const synced = user && user.prefs && user.prefs.reader && typeof user.prefs.reader === "object"
    ? user.prefs.reader : {};
  const merged = { ...READER_DEFAULTS, ...local, ...synced };
  if (!["default", "sepia", "night"].includes(merged.tone)) merged.tone = "default";
  return merged;
}

/* ---------- Settings (Aa) panel ---------- */
export function ReaderSettings({ prefs, setPrefs }) {
  const set = (k, v) => setPrefs(p => ({ ...p, [k]: v }));
  return (
    <div className="reader-settings card" onClick={e => e.stopPropagation()}>
      <div className="rs-preview" style={{
        "--rs-font": prefs.font === "serif" ? "var(--serif)" : "var(--sans)",
        "--rs-size": prefs.size + "px",
        "--rs-line": prefs.line,
      }}>
        The tide pulled back slowly, and for the first time the glass beneath the water caught the morning light.
      </div>
      <div className="rs-row">
        <span className="rs-label">Font</span>
        <SegmentedControl value={prefs.font} onChange={v => set("font", v)} ariaLabel="Font"
          options={[{ value: "serif", label: "Serif" }, { value: "sans", label: "Sans" }]} />
      </div>
      <div className="rs-row">
        <span className="rs-label">Size <span className="rs-value">{prefs.size}px</span></span>
        <input type="range" className="slider" min={14} max={28} step={1} value={prefs.size}
               aria-label="Font size" onChange={e => set("size", Number(e.target.value))} />
      </div>
      <div className="rs-row">
        <span className="rs-label">Line height <span className="rs-value">{prefs.line.toFixed(1)}</span></span>
        <input type="range" className="slider" min={1.3} max={2.2} step={0.1} value={prefs.line}
               aria-label="Line height" onChange={e => set("line", Math.round(Number(e.target.value) * 10) / 10)} />
      </div>
      <div className="rs-row">
        <span className="rs-label">Width</span>
        <SegmentedControl value={prefs.width} onChange={v => set("width", v)} ariaLabel="Column width"
          options={[{ value: "narrow", label: "Narrow" }, { value: "normal", label: "Normal" }, { value: "wide", label: "Wide" }, { value: "full", label: "Full" }]} />
      </div>
      <div className="rs-row">
        <span className="rs-label">Tone</span>
        <SegmentedControl value={prefs.tone} onChange={v => set("tone", v)} ariaLabel="Reading tone"
          options={[{ value: "default", label: "App" }, { value: "sepia", label: "Sepia" }, { value: "night", label: "Night" }]} />
      </div>
      <div className="rs-row">
        <span className="rs-label">Paragraphs</span>
        <div className="row" style={{ gap: 14 }}>
          <label className="check"><input type="checkbox" checked={!!prefs.justify} onChange={e => set("justify", e.target.checked)} /> Justify</label>
          <label className="check"><input type="checkbox" checked={!!prefs.indent} onChange={e => set("indent", e.target.checked)} /> Indent</label>
        </div>
      </div>
      <div className="rs-row">
        <span className="rs-label">Auto-scroll <span className="rs-value">{prefs.autoScroll ? `speed ${prefs.autoSpeed}` : "off"}</span></span>
        <div className="row" style={{ gap: 10 }}>
          <SegmentedControl fit value={prefs.autoScroll} onChange={v => set("autoScroll", v)} ariaLabel="Auto-scroll"
            options={[{ value: false, label: "Off" }, { value: true, label: "On" }]} />
          <input type="range" className="slider" min={1} max={10} step={1} value={prefs.autoSpeed}
                 aria-label="Auto-scroll speed" style={{ flex: 1 }}
                 onChange={e => set("autoSpeed", Number(e.target.value))} />
        </div>
      </div>
    </div>
  );
}

/* ---------- Translation tools ---------- */
export function TranslationTools({ novelId, ch, onClose, onChanged }) {
  const [draft, setDraft] = useState(ch.content || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const canEditBase = !!ch.can_edit_base;
  const hasOverlay = !!ch.overlay;
  const conflict = !!ch.overlay_conflict;
  const isOwner = !!ch.is_owner;

  const run = (fn, reload = true) => async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await fn();
      if (reload) { onChanged(); } else { setBusy(false); }
      return r;
    } catch (e) {
      setMsg({ ok: false, text: e.message || "Something went wrong." });
      setBusy(false);
    }
  };

  const saveBase = run(() => readingApi.editBaseContent(novelId, ch.number, draft));
  const saveMine = run(() => readingApi.saveOverlay(novelId, ch.number, draft));
  const selfTranslate = run(() => readingApi.selfTranslate(novelId, ch.number));
  const revert = run(() => readingApi.deleteOverlay(novelId, ch.number));
  const resolveMine = run(() => readingApi.resolveOverlay(novelId, ch.number, "mine"));
  const resolveBase = run(() => readingApi.resolveOverlay(novelId, ch.number, "base"));
  const resolveMerge = run(() => readingApi.resolveOverlay(novelId, ch.number, "merge", draft));

  async function offer() {
    setBusy(true); setMsg(null);
    try {
      const r = await readingApi.contribute(novelId, ch.number);
      if (r.status === "auto_merged") { onChanged(); return; }
      setMsg({ ok: true, text: "Sent to the owner for review." });
      setBusy(false);
    } catch (e) { setMsg({ ok: false, text: e.message || "Couldn't offer this edit." }); setBusy(false); }
  }

  return (
    <div className="translate-tools card" onClick={e => e.stopPropagation()}>
      <div className="row" style={{ marginBottom: 10 }}>
        <b className="grow">{canEditBase ? "Edit translation (shared)" : "Your translation"}</b>
        <button className="icon-btn plain" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button>
      </div>

      {conflict && (
        <div className="tt-conflict">
          <div style={{ fontWeight: 600, marginBottom: 4 }}>The shared base changed since your version.</div>
          <p className="muted" style={{ fontSize: "var(--text-xs)", margin: "0 0 8px" }}>
            Keep yours, switch to the latest base, or edit below and Save to merge.
          </p>
          {ch.base_content && (
            <DiffView oldText={ch.base_content} newText={ch.content || ""} oldLabel="Latest base" newLabel="Your version" />
          )}
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <Button variant="ghost" size="sm" disabled={busy} onClick={resolveMine}>Keep mine</Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={resolveBase}>Use latest base</Button>
          </div>
        </div>
      )}

      <textarea className="tt-textarea" value={draft} disabled={busy}
                onChange={e => setDraft(e.target.value)} rows={12} placeholder="Chapter translation…" />

      {msg && <div className={msg.ok ? "acct-ok" : "acct-err"} style={{ marginTop: 8 }}>{msg.text}</div>}

      <div className="row wrap" style={{ gap: 8, marginTop: 10 }}>
        {canEditBase
          ? <Button variant="primary" disabled={busy || !draft.trim()} onClick={saveBase}>Save for everyone</Button>
          : conflict
            ? <Button variant="primary" disabled={busy || !draft.trim()} onClick={resolveMerge}>Save merged</Button>
            : <Button variant="primary" disabled={busy || !draft.trim()} onClick={saveMine}>Save my version</Button>}
        {ch.has_original && (
          <Button variant="ghost" icon="refresh" disabled={busy} onClick={selfTranslate}
                  title="Re-translate this raw chapter into your own copy (uses quota)">
            Re-translate for me
          </Button>
        )}
        {hasOverlay && !canEditBase && !isOwner && (
          <Button variant="ghost" icon="send" disabled={busy} onClick={offer} title="Offer your version to the owner">
            Offer to owner
          </Button>
        )}
        {hasOverlay && <Button variant="ghost" className="is-danger" disabled={busy} onClick={revert}>Revert to original</Button>}
      </div>
    </div>
  );
}

/* ---------- Audio player ---------- */
export function AudioPlayer({ novelId, number, ch, user, onUserUpdate, openReader, onAudioChange, autoEngage }) {
  const [voices, setVoices] = useState(null);
  const [voice, setVoice] = useState(() => readTtsPrefs(user).voice);
  const [defaultVoice, setDefaultVoice] = useState(null);
  const [speed, setSpeed] = useState(() => readTtsPrefs(user).speed);
  const [src, setSrc] = useState(null);
  const [state, setState] = useState("idle");          // idle|checking|generating|ready|error|untranslated
  const [msg, setMsg] = useState(null);
  const [availableVoices, setAvailableVoices] = useState([]);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const audioRef = useRef(null);
  const pollRef = useRef(null);
  const posKey = `nw-tts:${novelId}:${number}:${voice || "none"}`;

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

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
    setSrc(null); setMsg(null); setAvailableVoices([]);
    setCur(0); setDur(0); setPlaying(false);
    if (!voice) { setState("idle"); return; }
    let cancel = false;
    setState("checking");
    narrationApi.chapterAudioStatus(novelId, number, voice).then(r => {
      if (cancel) return;
      setAvailableVoices(r.available_voices || []);
      if (r.cached) {
        setSrc(narrationApi.chapterAudioUrl(novelId, number, voice));
        setState("ready");
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

  async function loadReadyAudio(force) {
    const r = await narrationApi.chapterAudioStatus(novelId, number, voice);
    setAvailableVoices(r.available_voices || []);
    if (r.cached) {
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

  function watchJob(jobId, force) {
    stopPoll();
    setState("generating");
    pollRef.current = setInterval(async () => {
      try {
        const j = await narrationApi.ttsJob(jobId);
        if (j.status === "done") {
          stopPoll();
          const ok = await loadReadyAudio(force);
          if (!ok) { setState("error"); setMsg("Narration finished, but no playable audio was produced."); }
        } else if (j.status === "failed") {
          stopPoll(); setState("error"); setMsg(j.error || "Narration failed.");
        } else if (j.status === "canceled") {
          stopPoll(); setState("idle");
        }
      } catch (e) { stopPoll(); setState("error"); setMsg(e.message || "Narration failed."); }
    }, 1500);
  }

  async function generate(force) {
    if (!voice) return;
    setState("generating"); setMsg(null); stopPoll();
    try {
      const r = await narrationApi.generateChapterAudio(novelId, number, voice, force);
      if (r.status === "ready") {
        setSrc(narrationApi.chapterAudioUrl(novelId, number, voice) + (force ? `&t=${Date.now()}` : ""));
        setState("ready");
        onAudioChange && onAudioChange();
        return;
      }
      if (r.job_id) watchJob(r.job_id, force);
    } catch (e) {
      if (e.status === 409) { setState("untranslated"); setMsg("Translate this chapter before narrating it."); }
      else if (e.status === 429) { setState("error"); setMsg(e.message || "Monthly narration quota reached."); }
      else { setState("error"); setMsg(e.message || "Couldn't start narration."); }
    }
  }

  function togglePlay() {
    const a = audioRef.current; if (!a) return;
    if (a.paused) { const p = a.play(); if (p && p.catch) p.catch(() => {}); } else { a.pause(); }
  }
  function skip(delta) {
    const a = audioRef.current; if (!a) return;
    a.currentTime = clamp(a.currentTime + delta, 0, a.duration || 0);
    setCur(a.currentTime);
  }
  function seek(e) {
    const a = audioRef.current; const t = Number(e.target.value);
    setCur(t); if (a) a.currentTime = t;
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

  return (
    <div className="audio-bar" onClick={e => e.stopPropagation()}>
      {state === "ready" && src ? (
        <>
          <audio
            ref={audioRef} src={src} preload="metadata" style={{ display: "none" }}
            onPlay={() => { __ttsContinue = true; setPlaying(true); }}
            onPause={() => { __ttsContinue = false; setPlaying(false); }}
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
              if (Math.floor(a.currentTime) % 5 === 0) localStorage.setItem(posKey, String(a.currentTime));
            }}
            onEnded={() => {
              localStorage.removeItem(posKey); setPlaying(false);
              if (readTtsPrefs(user).autoplay && ch && ch.next != null) openReader(ch.next);
            }}
          />
          <button className="ab-skip" aria-label="Back 15 seconds" onClick={() => skip(-15)}>
            <Icon name="history" size={20} />
          </button>
          <button className="ab-play" onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>
            <Icon name={playing ? "pause" : "play"} size={17} />
          </button>
          <button className="ab-skip" aria-label="Forward 15 seconds" onClick={() => skip(15)}>
            <Icon name="refresh" size={20} />
          </button>
          <input type="range" className="ab-seek" min={0} max={dur || 0} step={0.1} value={Math.min(cur, dur || 0)}
                 onChange={seek} style={{ "--pct": pct + "%" }} aria-label="Seek" />
          <span className="ab-time">{fmt(cur)} / {fmt(dur)}</span>
          <button className="ab-speed" onClick={cycleSpeed} aria-label="Playback speed">{speed}×</button>
          {picker}
          <button className="icon-btn plain" style={{ width: 30, height: 30 }} title="Regenerate this narration"
                  aria-label="Regenerate narration" onClick={() => generate(true)}>
            <Icon name="refresh" size={14} />
          </button>
        </>
      ) : state === "generating" || state === "checking" ? (
        <>
          {picker}
          <span className="ab-status"><Icon name="refresh" size={14} className="spin" /> {state === "generating" ? "Narrating…" : "Checking…"}</span>
        </>
      ) : (
        <>
          {picker}
          <Button variant="ghost" size="sm" icon="play" onClick={() => generate(false)}
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
          {msg && <span className="ab-msg">{msg}</span>}
        </>
      )}
    </div>
  );
}

/* ---------- End-of-chapter card ---------- */
export function EndOfChapterCard({ ch, novelId, onNext, onPrev }) {
  const navigate = useNavigate();
  const nextIsRaw = ch.next != null && ch.next_is_raw;
  return (
    <div className="card eoc">
      <span className="eoc-mark"><Icon name="check" size={20} sw={2.2} /></span>
      <span className="eoc-done">Chapter {fmtChapter(ch.number)} complete</span>
      {ch.next != null ? (
        <>
          <h3 className="eoc-next-title">
            Next: Chapter {fmtChapter(ch.next)}
            {ch.next_title ? <> — <em>{ch.next_title}</em></> : null}
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
          <p className="muted" style={{ margin: 0, fontSize: "var(--text-sm)" }}>That's the last chapter for now.</p>
        </>
      )}
      <div className="eoc-links">
        {ch.prev != null && <button className="linkish" onClick={onPrev}><Icon name="arrowLeft" size={13} /> Previous</button>}
        <button className="linkish" onClick={() => navigate(`/n/${novelId}/chapters`)}>Contents</button>
      </div>
    </div>
  );
}

/* ---------- Reader ---------- */
export function RichContent({ html }) {
  const [lightbox, setLightbox] = useState(null);
  const onClick = (e) => {
    const img = e.target.closest("img");
    if (img && img.src) { e.stopPropagation(); setLightbox(img.src); }
  };
  return (
    <>
      <div className="reader-text reader-rich" onClick={onClick} dangerouslySetInnerHTML={{ __html: html }} />
      {lightbox && (
        <div className="lightbox-scrim" onClick={(e) => { e.stopPropagation(); setLightbox(null); }}>
          <img src={lightbox} alt="" />
        </div>
      )}
    </>
  );
}

