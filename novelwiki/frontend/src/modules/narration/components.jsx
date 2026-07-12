/* ============================================================
   Narration — the shared VoicePicker and the whole-book NarrateBookControl
   (deduplicates the old reader/novel voice UIs).
   ============================================================ */
import React, { useEffect, useRef, useState } from "react";
import { experienceApi } from "../experience/api.js";
import { narrationApi } from "./api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, ProgressBar } from "../../components/ui.jsx";
import { Popover, MenuItem, CostConfirmDialog } from "../../components/overlay.jsx";
import { ttsVoiceMeta } from "../reading/index.js";

export function readTtsPrefs(user) {
  const p = (user && user.prefs && user.prefs.tts) || {};
  return { voice: p.voice || null, speed: Number(p.speed) || 1, autoplay: p.autoplay !== false };
}

/* Compact popover voice picker. `voices` = ready voices; badges preferred/default. */
export function VoicePicker({ voices, value, onChange, defaultVoice, preferredVoice, coverage, proseChapters }) {
  const [open, setOpen] = useState(false);
  const current = (voices || []).find(v => v.id === value);
  const covByVoice = coverage ? new Map(coverage.map(v => [v.voice_id, v])) : null;
  return (
    <Popover open={open} onClose={() => setOpen(false)} className="voice-menu" trigger={
      <button className="voice-pill" aria-expanded={open} onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }} title="Narrator voice">
        <Icon name="headphones" size={13} />
        <span className="vp-name">{current ? (current.name || current.id) : "Voice"}</span>
        <Icon name="chevronDown" size={12} />
      </button>
    }>
      {(voices || []).map(v => {
        const meta = ttsVoiceMeta(v);
        const cov = covByVoice && covByVoice.get(v.id);
        const badges = [
          preferredVoice === v.id ? "preferred" : (defaultVoice === v.id ? "default" : null),
          cov && proseChapters ? `${cov.have}/${proseChapters} narrated` : null,
        ].filter(Boolean).join(" · ");
        return (
          <MenuItem key={v.id} selected={v.id === value}
                    onClick={(e) => { e.stopPropagation(); setOpen(false); onChange(v.id); }}>
            {v.name || v.id}
            {(meta || badges) && <span className="vm-meta">{[meta, badges].filter(Boolean).join(" · ")}</span>}
          </MenuItem>
        );
      })}
    </Popover>
  );
}

/* Whole-book narration: pick a narrator + range, queue a bounded cancellable
   batch (cost-confirmed), show live progress. */
export function NarrateBookControl({ novelId, novel, user, audioCoverage, onChange }) {
  const [open, setOpen] = useState(false);
  const [voices, setVoices] = useState(null);   // null=loading | [] offline
  const [voice, setVoice] = useState(null);
  const [defaultVoice, setDefaultVoice] = useState(null);
  const minCh = novel?.min_chapter != null ? String(novel.min_chapter) : "";
  const [startCh, setStartCh] = useState(minCh);
  const [endCh, setEndCh] = useState("");
  const [job, setJob] = useState(null);
  const [msg, setMsg] = useState(null);
  const [est, setEst] = useState(null);
  const [pendingStart, setPendingStart] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => { setStartCh(minCh); }, [minCh]);

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => () => stopPoll(), []);

  useEffect(() => {
    narrationApi.ttsVoices().then(r => {
      const list = (r.voices || []).filter(v => v.ready);
      setVoices(list);
      setDefaultVoice(r.default || null);
      const pref = readTtsPrefs(user).voice;
      const ids = new Set(list.map(v => v.id));
      setVoice((pref && ids.has(pref)) ? pref : ((r.default && ids.has(r.default)) ? r.default : ((list[0] && list[0].id) || null)));
    }).catch(() => setVoices([]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function poll(id) {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const j = await narrationApi.ttsJob(id);
        setJob(j);
        if (["done", "failed", "canceled"].includes(j.status)) { stopPoll(); onChange && onChange(); }
      } catch (e) { stopPoll(); }
    }, 1800);
  }

  // If a batch for this voice is already running (from another session), adopt it.
  useEffect(() => {
    if (!voice) return;
    let cancel = false;
    narrationApi.bookAudioStatus(novelId, voice).then(r => {
      if (cancel) return;
      if (r.active && r.job) {
        setMsg(null);
        setJob(r.job);
        setOpen(true);
        poll(r.job.id);
      } else {
        setJob(j => j && ["queued", "generating"].includes(j.status) ? null : j);
      }
    }).catch(() => {});
    return () => { cancel = true; };
  }, [novelId, voice]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pre-flight estimate for the current range/voice. Never charges.
  useEffect(() => {
    if (!open || !voice) { setEst(null); return; }
    let cancel = false;
    experienceApi.costEstimate(novelId, "audiobook", {
      voice_id: voice,
      from_chapter: startCh.trim() ? parseFloat(startCh) : null,
      to_chapter: endCh.trim() ? parseFloat(endCh) : null,
    }).then(e => { if (!cancel) setEst(e); }).catch(() => { if (!cancel) setEst(null); });
    return () => { cancel = true; };
  }, [open, voice, startCh, endCh, novelId]);

  const narrationParams = () => ({
    voice_id: voice,
    from_chapter: startCh.trim() ? parseFloat(startCh) : null,
    to_chapter: endCh.trim() ? parseFloat(endCh) : null,
  });

  async function start(params) {
    const p = params || narrationParams();
    if (!p.voice_id) return;
    setMsg(null); setJob(null);
    try {
      const r = await narrationApi.generateBookAudio(novelId, p.voice_id, p.from_chapter, p.to_chapter);
      if (r.status === "ready") { setMsg(r.message || "Every chapter is already narrated in this voice."); return; }
      setMsg(r.existing
        ? "Already narrating this book in that voice."
        : r.capped
          ? `Queued ${r.total} chapters (max per batch — run again for more).`
          : `Queued ${r.total} chapter${r.total === 1 ? "" : "s"}.`);
      setJob({ id: r.job_id, status: "queued", progress: { total: r.total, done: 0 } });
      poll(r.job_id);
    } catch (e) {
      setMsg(e.status === 429 ? (e.message || "Monthly narration quota reached.") : (e.message || "Couldn't start narration."));
    }
  }

  async function cancel() {
    if (!job) return;
    try { await narrationApi.cancelTtsJob(job.id); } catch (e) { /* already finished */ }
  }

  if (voices == null || voices.length === 0) return null;   // hidden while loading / sidecar offline

  const running = job && ["queued", "generating"].includes(job.status);
  const prog = (job && job.progress) || {};
  const pct = prog.total ? Math.round((100 * (prog.done || 0)) / prog.total) : 0;
  const stopped = prog.stopped_reason;
  const prefVoice = readTtsPrefs(user).voice;
  const selectedVoice = (voices || []).find(v => v.id === voice);
  const coverageByVoice = new Map(((audioCoverage && audioCoverage.voices) || []).map(v => [v.voice_id, v]));
  const selectedCoverage = coverageByVoice.get(voice) || { have: 0 };

  return (
    <Popover open={open} onClose={() => setOpen(false)} align="left" className="narrate-panel" trigger={
      <Button variant="ghost" icon="headphones" aria-expanded={open} onClick={() => setOpen(o => !o)}>Narrate book</Button>
    }>
      <div onClick={e => e.stopPropagation()}>
        <div className="row wrap" style={{ gap: 8, alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 130 }}>
            <span>Narrator</span>
            <VoicePicker voices={voices} value={voice} onChange={setVoice}
                         defaultVoice={defaultVoice} preferredVoice={prefVoice}
                         coverage={(audioCoverage && audioCoverage.voices) || null}
                         proseChapters={audioCoverage && audioCoverage.prose_chapters} />
          </div>
          <label className="field" style={{ flex: "0 0 76px" }}>
            <span>From Ch.</span>
            <input value={startCh} onChange={e => setStartCh(e.target.value)} placeholder={minCh || "1"} inputMode="numeric" />
          </label>
          <label className="field" style={{ flex: "0 0 76px" }}>
            <span>To Ch.</span>
            <input value={endCh} onChange={e => setEndCh(e.target.value)} placeholder="end" inputMode="numeric" />
          </label>
        </div>

        {selectedVoice && (
          <div className="voice-detail">
            <span className="voice-name">{selectedVoice.name || selectedVoice.id}</span>
            <span className="mono">{selectedVoice.id}</span>
            {ttsVoiceMeta(selectedVoice) && <span>{ttsVoiceMeta(selectedVoice)}</span>}
            {prefVoice === selectedVoice.id && <Chip tone="accent">preferred</Chip>}
            {defaultVoice === selectedVoice.id && <Chip>default</Chip>}
            {audioCoverage && <span>{selectedCoverage.have || 0}/{audioCoverage.prose_chapters} chapters narrated</span>}
            {(selectedVoice.description || selectedVoice.note) && <span className="voice-note">{selectedVoice.description || selectedVoice.note}</span>}
          </div>
        )}

        {!running && est && (
          <div className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 10 }}>
            {est.estimated_units === 0
              ? "Every chapter in this range is already narrated in this voice."
              : `~${est.estimated_units} chapter${est.estimated_units === 1 ? "" : "s"} to narrate` +
                (est.capped ? " (capped this batch)" : "") +
                (est.unlimited ? "" : ` · ${est.remaining}/${est.limit} quota left this month`)}
          </div>
        )}

        <div className="row" style={{ gap: 8, marginTop: 10 }}>
          {running
            ? <Button variant="ghost" className="is-danger" icon="x" onClick={cancel}>Cancel</Button>
            : <Button variant="primary" icon="play" disabled={!voice} onClick={() => setPendingStart(narrationParams())}>Start narrating</Button>}
        </div>

        {job && (
          <div style={{ marginTop: 12 }}>
            <ProgressBar size="sm" value={pct} label="Narration progress" />
            <div className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 6 }}>
              {`${prog.done || 0} / ${prog.total || 0} narrated`}
              {prog.skipped ? ` · ${prog.skipped} skipped` : ""}
              {stopped === "quota" ? " · stopped: monthly quota reached"
                : stopped === "canceled" ? " · canceled"
                : job.status === "done" ? " · done"
                : job.status === "failed" ? " · failed" : ""}
            </div>
          </div>
        )}
        {job && job.status === "failed" && job.error && <div className="acct-err" style={{ marginTop: 8 }}>{job.error}</div>}
        {msg && !job && <div className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 8 }}>{msg}</div>}
        <p className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 10, marginBottom: 0 }}>
          Generates audio on the server and caches it for everyone. Capped per batch; re-run to continue a long book.
        </p>
      </div>
      {pendingStart && (
        <CostConfirmDialog
          novelId={novelId} action="audiobook" params={pendingStart}
          title="Narrate book" actionLabel="Start narration"
          onCancel={() => setPendingStart(null)}
          onConfirm={async () => { await start(pendingStart); setPendingStart(null); }} />
      )}
    </Popover>
  );
}
