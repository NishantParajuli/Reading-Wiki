/* ============================================================
   Reader — the reading surface. Typeset chapter text, prev/next, a TOC drawer,
   bookmark toggle, and reader display settings (font/size/line-height/width/tone)
   persisted to localStorage. Reading progress (last chapter + scroll) is saved to
   the server so the library can resume and the codex ceiling can follow along.
   ============================================================ */
const READER_DEFAULTS = { font: "serif", size: 19, line: 1.7, width: "normal", tone: "default", autoScroll: false, autoSpeed: 3 };
const WIDTHS = { narrow: 620, normal: 760, wide: 960, ultra: 1200 };
// Auto-scroll: speed 1..10 maps to px/second (gentle reading pace ≈ 28–280 px/s).
const AUTOSCROLL_PX_PER_SEC = (speed) => Math.max(1, speed) * 28;

function loadReaderPrefs(user) {
  let local = {};
  try { local = JSON.parse(localStorage.getItem("nw-reader") || "{}") || {}; }
  catch (e) { local = {}; }
  const synced = user && user.prefs && user.prefs.reader && typeof user.prefs.reader === "object"
    ? user.prefs.reader : {};
  return { ...READER_DEFAULTS, ...local, ...synced };
}

function ReaderSettings({ prefs, setPrefs, onClose }) {
  const set = (k, v) => setPrefs(p => ({ ...p, [k]: v }));
  const Row = (label, children) => React.createElement("div", { className: "rs-row" },
    React.createElement("span", { className: "rs-label" }, label), children);
  const seg = (k, opts) => React.createElement("div", { className: "rs-seg" },
    opts.map(o => React.createElement("button", {
      key: o.v, className: prefs[k] === o.v ? "active" : "", onClick: () => set(k, o.v),
    }, o.t)));

  return React.createElement("div", { className: "reader-settings card", onClick: e => e.stopPropagation() },
    Row("Font", seg("font", [{ v: "serif", t: "Serif" }, { v: "sans", t: "Sans" }])),
    Row("Size", React.createElement("div", { className: "rs-seg" },
      React.createElement("button", { onClick: () => set("size", Math.max(14, prefs.size - 1)) }, "A−"),
      React.createElement("span", { className: "rs-val" }, prefs.size),
      React.createElement("button", { onClick: () => set("size", Math.min(28, prefs.size + 1)) }, "A+"))),
    Row("Line height", React.createElement("div", { className: "rs-seg" },
      React.createElement("button", { onClick: () => set("line", Math.max(1.3, Math.round((prefs.line - 0.1) * 10) / 10)) }, "−"),
      React.createElement("span", { className: "rs-val" }, prefs.line.toFixed(1)),
      React.createElement("button", { onClick: () => set("line", Math.min(2.2, Math.round((prefs.line + 0.1) * 10) / 10)) }, "+"))),
    Row("Width", seg("width", [{ v: "narrow", t: "Narrow" }, { v: "normal", t: "Normal" }, { v: "wide", t: "Wide" }, { v: "ultra", t: "Ultra" }])),
    Row("Tone", seg("tone", [{ v: "default", t: "Default" }, { v: "sepia", t: "Sepia" }])),
    Row("Auto-scroll", seg("autoScroll", [{ v: false, t: "Off" }, { v: true, t: "On" }])),
    Row("Scroll speed", React.createElement("div", { className: "rs-seg" },
      React.createElement("button", { onClick: () => set("autoSpeed", Math.max(1, prefs.autoSpeed - 1)) }, "−"),
      React.createElement("span", { className: "rs-val" }, prefs.autoSpeed),
      React.createElement("button", { onClick: () => set("autoSpeed", Math.min(10, prefs.autoSpeed + 1)) }, "+"))),
    React.createElement("button", { className: "btn btn-ghost", style: { width: "100%", marginTop: 8 }, onClick: onClose }, "Done")
  );
}

/* Translation tools panel (Phase 5): edit the shared base (owner/admin) or your personal
   overlay, self-translate a raw chapter, offer your edit back to the owner, and resolve a
   conflict when the shared base has moved on since your overlay. */
function TranslationTools({ novelId, ch, onClose, onChanged }) {
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

  const saveBase = run(() => window.API.editBaseContent(novelId, ch.number, draft));
  const saveMine = run(() => window.API.saveOverlay(novelId, ch.number, draft));
  const selfTranslate = run(() => window.API.selfTranslate(novelId, ch.number));
  const revert = run(() => window.API.deleteOverlay(novelId, ch.number));
  const resolveMine = run(() => window.API.resolveOverlay(novelId, ch.number, "mine"));
  const resolveBase = run(() => window.API.resolveOverlay(novelId, ch.number, "base"));
  const resolveMerge = run(() => window.API.resolveOverlay(novelId, ch.number, "merge", draft));

  async function offer() {
    setBusy(true); setMsg(null);
    try {
      const r = await window.API.contribute(novelId, ch.number);
      if (r.status === "auto_merged") { onChanged(); return; }
      setMsg({ ok: true, text: "Sent to the owner for review." });
      setBusy(false);
    } catch (e) { setMsg({ ok: false, text: e.message || "Couldn't offer this edit." }); setBusy(false); }
  }

  const h = React.createElement;
  return h("div", { className: "translate-tools card", onClick: e => e.stopPropagation() },
    h("div", { className: "row", style: { alignItems: "center", marginBottom: 10 } },
      h("b", { className: "grow" }, canEditBase ? "Edit translation (shared)" : "Your translation"),
      h("button", { className: "icon-btn", onClick: onClose }, h(Icon, { name: "x", size: 16 }))
    ),

    conflict && h("div", { className: "tt-conflict" },
      h("div", { style: { fontWeight: 600, marginBottom: 4 } }, "The shared base changed since your version."),
      h("p", { className: "muted", style: { fontSize: 12.5, margin: "0 0 8px" } },
        "Keep yours, switch to the latest base, or edit below and Save to merge."),
      // GitHub-style diff: latest base on top, your version below with +/- changes.
      ch.base_content && h(window.DiffView, {
        oldText: ch.base_content, newText: ch.content || "",
        oldLabel: "Latest base", newLabel: "Your version",
      }),
      h("div", { className: "row", style: { gap: 8, marginTop: 8 } },
        h("button", { className: "btn btn-ghost", disabled: busy, onClick: resolveMine }, "Keep mine"),
        h("button", { className: "btn btn-ghost", disabled: busy, onClick: resolveBase }, "Use latest base")
      )
    ),

    h("textarea", {
      className: "tt-textarea", value: draft, disabled: busy,
      onChange: e => setDraft(e.target.value), rows: 12, placeholder: "Chapter translation…",
    }),

    msg && h("div", { className: msg.ok ? "acct-ok" : "acct-err", style: { marginTop: 8 } }, msg.text),

    h("div", { className: "row", style: { gap: 8, marginTop: 10, flexWrap: "wrap" } },
      canEditBase
        ? h("button", { className: "btn btn-primary", disabled: busy || !draft.trim(), onClick: saveBase }, "Save for everyone")
        : conflict
          ? h("button", { className: "btn btn-primary", disabled: busy || !draft.trim(), onClick: resolveMerge }, "Save merged")
          : h("button", { className: "btn btn-primary", disabled: busy || !draft.trim(), onClick: saveMine }, "Save my version"),
      ch.has_original && h("button", { className: "btn btn-ghost", disabled: busy, onClick: selfTranslate, title: "Re-translate this raw chapter into your own copy (uses quota)" },
        h(Icon, { name: "refresh", size: 15 }), "Re-translate for me"),
      hasOverlay && !canEditBase && !isOwner && h("button", { className: "btn btn-ghost", disabled: busy, onClick: offer, title: "Offer your version to the owner" },
        h(Icon, { name: "send", size: 15 }), "Offer to owner"),
      hasOverlay && h("button", { className: "btn btn-ghost is-danger", disabled: busy, onClick: revert }, "Revert to original")
    )
  );
}

/* Audiobook player (Phase: TTS). A slim persistent bar under the toolbar: pick a narrator,
   generate this chapter's narration on demand (durable job; we poll until ready), then play
   with seek/speed. Position is remembered per chapter and playback auto-advances to the next
   chapter so a hands-free listen flows continuously. Generated audio is cached server-side and
   shared across readers, so a chapter is only ever synthesized once per voice. */
const TTS_SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];
// Module-level intent flag so auto-advance keeps playing into the next chapter (set once the
// user presses play; cleared when they pause).
let __ttsContinue = false;

function readTtsPrefs(user) {
  const p = (user && user.prefs && user.prefs.tts) || {};
  return { voice: p.voice || null, speed: Number(p.speed) || 1, autoplay: p.autoplay !== false };
}

function AudioBar({ novelId, number, ch, user, onUserUpdate, openReader }) {
  const [voices, setVoices] = useState(null);          // null=loading | [] none/offline
  const [voice, setVoice] = useState(() => readTtsPrefs(user).voice);
  const [speed, setSpeed] = useState(() => readTtsPrefs(user).speed);
  const [src, setSrc] = useState(null);                // audio URL once ready
  const [state, setState] = useState("idle");          // idle|checking|generating|ready|error|untranslated
  const [msg, setMsg] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [cur, setCur] = useState(0);                   // current playback time (s)
  const [dur, setDur] = useState(0);                   // total duration (s)
  const audioRef = useRef(null);
  const pollRef = useRef(null);
  const posKey = `nw-tts:${novelId}:${number}`;

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

  // Narrator catalog (ready voices only). Default from prefs → server default → first ready.
  useEffect(() => {
    let cancel = false;
    window.API.ttsVoices().then(r => {
      if (cancel) return;
      const list = (r.voices || []).filter(v => v.ready);
      setVoices(list);
      setVoice(v => v || readTtsPrefs(user).voice || r.default || (list[0] && list[0].id) || null);
    }).catch(() => { if (!cancel) setVoices([]); });
    return () => { cancel = true; };
  }, []);

  // On chapter/voice change: drop any loaded audio and check whether this chapter is already
  // cached for the chosen voice (→ ready to play, possibly auto-played from the previous one).
  useEffect(() => {
    stopPoll(); setSrc(null); setMsg(null);
    if (!voice) { setState("idle"); return; }
    let cancel = false;
    setState("checking");
    window.API.chapterAudioStatus(novelId, number, voice).then(r => {
      if (cancel) return;
      if (r.cached) {
        setSrc(window.API.chapterAudioUrl(novelId, number, voice));
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
  }, [novelId, number, voice]);

  // Apply playback speed to the element whenever it (or the speed) changes.
  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = speed; }, [speed, src]);

  // If we arrived here mid-listen (auto-advance) and the audio is ready, keep playing.
  useEffect(() => {
    if (state === "ready" && src && __ttsContinue && audioRef.current) {
      const p = audioRef.current.play();
      if (p && p.catch) p.catch(() => {});   // browsers may block; ignore
    }
  }, [state, src]);

  function persist(next) {
    if (!user) return;
    window.API.updateMe({ prefs: { tts: { voice, speed, ...next } } })
      .then(u => onUserUpdate && onUserUpdate(u)).catch(() => {});
  }
  function pickVoice(v) { setVoice(v); persist({ voice: v }); }
  function pickSpeed(s) { setSpeed(s); if (audioRef.current) audioRef.current.playbackRate = s; persist({ speed: s }); }

  async function loadReadyAudio(force) {
    const r = await window.API.chapterAudioStatus(novelId, number, voice);
    if (r.cached) {
      setSrc(window.API.chapterAudioUrl(novelId, number, voice) + (force ? `&t=${Date.now()}` : ""));
      setState("ready");
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
        const j = await window.API.ttsJob(jobId);
        if (j.status === "done") {
          stopPoll();
          const ok = await loadReadyAudio(force);
          if (!ok) {
            setState("error");
            setMsg("Narration finished, but no playable audio was produced.");
          }
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
      const r = await window.API.generateChapterAudio(novelId, number, voice, force);
      if (r.status === "ready") {
        setSrc(window.API.chapterAudioUrl(novelId, number, voice) + (force ? `&t=${Date.now()}` : ""));
        setState("ready");
        return;
      }
      if (r.job_id) watchJob(r.job_id, force);
    } catch (e) {
      if (e.status === 409) { setState("untranslated"); setMsg("Translate this chapter before narrating it."); }
      else if (e.status === 429) { setState("error"); setMsg(e.message || "Monthly narration quota reached."); }
      else { setState("error"); setMsg(e.message || "Couldn't start narration."); }
    }
  }

  // ── Transport (custom UI driving a headless <audio>) ──
  function togglePlay() {
    const a = audioRef.current; if (!a) return;
    if (a.paused) { const p = a.play(); if (p && p.catch) p.catch(() => {}); } else { a.pause(); }
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

  const h = React.createElement;
  // Hidden until the catalog resolves; if the sidecar is offline (no ready voices) stay hidden.
  if (voices == null) return null;
  if (voices.length === 0) return null;

  const voiceSel = h("div", { className: "ab-select" },
    h(Icon, { name: "headphones", size: 14, className: "ab-select-ic" }),
    h("select", {
      className: "ab-voice", value: voice || "", onChange: e => pickVoice(e.target.value),
      title: "Narrator voice", onClick: e => e.stopPropagation(),
    }, voices.map(v => h("option", { key: v.id, value: v.id },
      v.name + (v.accent ? ` · ${v.accent}` : "")))),
    h(Icon, { name: "chevronDown", size: 13, className: "ab-select-caret" }));

  const pct = dur > 0 ? (cur / dur) * 100 : 0;

  let body;
  if (state === "ready" && src) {
    body = h(React.Fragment, null,
      h("audio", {
        ref: audioRef, src, preload: "metadata", style: { display: "none" },
        onPlay: () => { __ttsContinue = true; setPlaying(true); },
        onPause: () => { __ttsContinue = false; setPlaying(false); },
        onDurationChange: () => setDur(audioRef.current ? audioRef.current.duration || 0 : 0),
        onLoadedMetadata: () => {
          const a = audioRef.current; if (!a) return;
          a.playbackRate = speed; setDur(a.duration || 0);
          const saved = parseFloat(localStorage.getItem(posKey) || "0");
          if (saved > 1 && saved < (a.duration || 1e9) - 2) { a.currentTime = saved; setCur(saved); }
        },
        onTimeUpdate: () => {
          const a = audioRef.current; if (!a) return;
          setCur(a.currentTime);
          if (Math.floor(a.currentTime) % 5 === 0) localStorage.setItem(posKey, String(a.currentTime));
        },
        onEnded: () => {
          localStorage.removeItem(posKey); setPlaying(false);
          if (readTtsPrefs(user).autoplay && ch && ch.next != null) openReader(ch.next);
        },
      }),
      h("button", { className: "ab-play", onClick: togglePlay, title: playing ? "Pause" : "Play" },
        h(Icon, { name: playing ? "pause" : "play", size: 18 })),
      h("input", {
        type: "range", className: "ab-seek", min: 0, max: dur || 0, step: 0.1, value: Math.min(cur, dur || 0),
        onChange: seek, style: { "--pct": pct + "%" }, "aria-label": "Seek",
      }),
      h("span", { className: "ab-time mono" }, `${fmt(cur)} / ${fmt(dur)}`),
      h("button", { className: "ab-speed", onClick: cycleSpeed, title: "Playback speed" }, speed + "×"),
      voiceSel,
      h("button", { className: "icon-btn ab-regen", title: "Regenerate this narration", onClick: () => generate(true) },
        h(Icon, { name: "refresh", size: 14 })));
  } else if (state === "generating" || state === "checking") {
    body = h(React.Fragment, null,
      voiceSel,
      h("span", { className: "ab-status muted" },
        h(Icon, { name: "refresh", size: 14, className: "spin" }),
        state === "generating" ? "Narrating…" : "Checking…"));
  } else {
    body = h(React.Fragment, null,
      voiceSel,
      h("button", { className: "btn btn-ghost ab-gen", onClick: () => generate(false) },
        h(Icon, { name: "play", size: 14 }), "Narrate chapter"),
      msg && h("span", { className: "ab-msg" }, msg));
  }

  return h("div", { className: "audio-bar", onClick: e => e.stopPropagation() }, body
  );
}

function Reader({ novelId, number, openReader, backToNovel, onRead, user, onUserUpdate }) {
  const [ch, setCh] = useState(null);     // null = loading
  const [status, setStatus] = useState("loading");
  const [prefs, setPrefs] = useState(() => loadReaderPrefs(user));
  const [showSettings, setShowSettings] = useState(false);
  const [toc, setToc] = useState(null);
  const [showToc, setShowToc] = useState(false);
  const [bookmarks, setBookmarks] = useState([]);
  const [chrome, setChrome] = useState(true);   // toolbar + floating nav visibility (tap to toggle)
  const [reloadKey, setReloadKey] = useState(0);
  const [showTools, setShowTools] = useState(false);   // translation overlay editor (Phase 5)
  const scrollSaved = useRef(0);

  useEffect(() => {
    localStorage.setItem("nw-reader", JSON.stringify(prefs));
    if (!user) return;
    const t = setTimeout(() => {
      window.API.updateMe({ prefs: { reader: prefs } })
        .then(u => { onUserUpdate && onUserUpdate(u); })
        .catch(() => {});
    }, 700);
    return () => clearTimeout(t);
  }, [prefs, user && user.id]);

  // Load the chapter + record progress. If we're reopening the exact chapter the
  // server says we last left off in, restore the saved scroll fraction so reading
  // resumes seamlessly across devices (the position lives server-side, not locally).
  useEffect(() => {
    let cancel = false;
    setStatus("loading"); setCh(null);
    window.scrollTo({ top: 0 });
    Promise.all([
      window.API.chapter(novelId, number),
      window.API.getProgress(novelId).catch(() => null),
    ])
      .then(([c, prog]) => {
        if (cancel) return;
        setCh(c);
        setStatus("ok");
        const resume = prog && Number(prog.last_chapter) === Number(number) ? (prog.scroll_pct || 0) : 0;
        // Keep the resume fraction rather than zeroing it, so the position survives a reopen.
        window.API.setProgress(novelId, { last_chapter: Number(number), scroll_pct: resume }).catch(() => {});
        scrollSaved.current = Date.now();   // don't immediately re-save right after restoring
        onRead && onRead(Number(number));
        if (resume > 0.002) {
          // Restore after the text lays out. Double rAF: first commits the DOM, second measures it.
          const applyScroll = () => {
            const h = document.documentElement;
            window.scrollTo({ top: resume * (h.scrollHeight - h.clientHeight) });
          };
          requestAnimationFrame(() => requestAnimationFrame(() => { if (!cancel) applyScroll(); }));
          // Imported rich chapters carry images that shift layout as they decode (even with
          // reserved width/height, lazy ones load late) — re-apply the saved fraction once
          // they finish so the restore doesn't land short.
          setTimeout(() => {
            if (cancel) return;
            const imgs = Array.from(document.querySelectorAll(".reader-rich img"));
            let pending = imgs.filter(im => !im.complete).length;
            if (!pending) return;
            const onDone = () => { if (--pending <= 0 && !cancel) applyScroll(); };
            imgs.forEach(im => { if (!im.complete) { im.addEventListener("load", onDone); im.addEventListener("error", onDone); } });
          }, 0);
        }
      })
      .catch(e => { if (!cancel) { setStatus(e.status === 404 ? "notfound" : "error"); } });
    return () => { cancel = true; };
  }, [novelId, number, reloadKey]);

  // Bookmarks for this novel (to toggle the current chapter).
  const loadBookmarks = useCallback(() => {
    window.API.bookmarks(novelId).then(setBookmarks).catch(() => setBookmarks([]));
  }, [novelId]);
  useEffect(() => { loadBookmarks(); }, [loadBookmarks]);

  // Throttled scroll-position save.
  useEffect(() => {
    const onScroll = () => {
      const h = document.documentElement;
      const pct = h.scrollHeight > h.clientHeight ? h.scrollTop / (h.scrollHeight - h.clientHeight) : 0;
      const now = Date.now();
      if (now - scrollSaved.current > 2000) {
        scrollSaved.current = now;
        window.API.setProgress(novelId, { last_chapter: number, scroll_pct: pct }).catch(() => {});
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [novelId, number]);

  // Auto-scroll engine: rAF nudges the page down at the chosen speed. At the bottom it
  // rolls into the next chapter so a hands-free read flows continuously. Sub-pixel
  // accumulation keeps slow speeds smooth instead of stuttering one pixel at a time.
  useEffect(() => {
    if (!prefs.autoScroll || status !== "ok" || !ch || (!ch.content && !ch.rich_html)) return;
    let raf, last = performance.now(), acc = 0;
    const step = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const h = document.documentElement;
      const maxTop = h.scrollHeight - h.clientHeight;
      if (maxTop > 4) {
        acc += AUTOSCROLL_PX_PER_SEC(prefs.autoSpeed) * dt;
        if (h.scrollTop >= maxTop - 1) {
          if (ch.next != null) { openReader(ch.next); return; }   // seamless next chapter
          return;                                                  // end of novel → stop
        }
        if (acc >= 1) { const dy = Math.floor(acc); acc -= dy; window.scrollBy(0, dy); }
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [prefs.autoScroll, prefs.autoSpeed, status, ch, openReader]);

  // Keyboard prev/next.
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === "ArrowLeft" && ch && ch.prev != null) openReader(ch.prev);
      if (e.key === "ArrowRight" && ch && ch.next != null) openReader(ch.next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ch]);

  function openTocDrawer() {
    if (toc == null) window.API.chapters(novelId).then(setToc).catch(() => setToc([]));
    setShowToc(true);
  }

  const bookmark = bookmarks.find(b => b.chapter === Number(number));
  async function toggleBookmark() {
    if (bookmark) { await window.API.delBookmark(novelId, bookmark.id); }
    else { await window.API.addBookmark(novelId, { chapter: Number(number) }); }
    loadBookmarks();
  }

  const fontFamily = prefs.font === "serif" ? 'var(--serif, "Newsreader", Georgia, serif)' : 'var(--sans, "Hanken Grotesk", system-ui, sans-serif)';
  const colStyle = {
    maxWidth: WIDTHS[prefs.width] || 720,
    fontFamily, fontSize: prefs.size, lineHeight: prefs.line,
  };

  // Tap the page (not a control) to toggle the toolbar + floating nav.
  const tapToggle = (e) => {
    if (e.target.closest("button, a, input, select, textarea, .reader-settings, .translate-tools, .drawer")) return;
    if (showSettings) { setShowSettings(false); return; }
    if (showTools) { setShowTools(false); return; }
    setChrome(c => !c);
  };

  return React.createElement("div", { className: "reader tone-" + prefs.tone + (chrome ? "" : " chrome-hidden"), onClick: tapToggle },
    // toolbar
    React.createElement("div", { className: "reader-bar" + (chrome ? "" : " hidden") },
      React.createElement("button", { className: "icon-btn", onClick: backToNovel, title: "Contents" },
        React.createElement(Icon, { name: "arrowLeft", size: 18 })),
      React.createElement("button", { className: "icon-btn", onClick: openTocDrawer, title: "Table of contents" },
        React.createElement(Icon, { name: "layers", size: 18 })),
      React.createElement("div", { className: "grow reader-bar-title" }, ch ? (ch.title || `Chapter ${ch.number}`) : "…"),
      React.createElement("button", {
        className: "icon-btn" + (prefs.autoScroll ? " active" : ""),
        onClick: e => { e.stopPropagation(); setPrefs(p => ({ ...p, autoScroll: !p.autoScroll })); },
        title: prefs.autoScroll ? "Stop auto-scroll" : "Auto-scroll",
      }, React.createElement(Icon, { name: prefs.autoScroll ? "pause" : "play", size: 17 })),
      React.createElement("button", { className: "icon-btn" + (bookmark ? " active" : ""), onClick: toggleBookmark, title: bookmark ? "Remove bookmark" : "Bookmark" },
        React.createElement(Icon, { name: bookmark ? "check" : "book", size: 18 })),
      // Translation tools: edit the shared base / your overlay, contribute back, resolve conflicts.
      status === "ok" && ch && (ch.content != null || ch.has_original) && React.createElement("div", { style: { position: "relative" } },
        React.createElement("button", {
          className: "icon-btn" + (ch.overlay ? " active" : "") + (ch.overlay_conflict ? " has-conflict" : ""),
          onClick: e => { e.stopPropagation(); setShowTools(s => !s); },
          title: ch.overlay_conflict ? "Translation update available" : (ch.overlay ? "Your translation edit" : "Edit translation"),
        }, React.createElement(Icon, { name: "edit", size: 17 }),
           ch.overlay_conflict && React.createElement("span", { className: "tt-badge" }, "1")),
        showTools && React.createElement(TranslationTools, {
          novelId, ch,
          onClose: () => setShowTools(false),
          onChanged: () => { setShowTools(false); setReloadKey(k => k + 1); },
        })
      ),
      React.createElement("div", { style: { position: "relative" } },
        React.createElement("button", { className: "icon-btn", onClick: e => { e.stopPropagation(); setShowSettings(s => !s); }, title: "Reading settings" },
          React.createElement("span", { style: { fontWeight: 700, fontSize: 15 } }, "Aa")),
        showSettings && React.createElement(ReaderSettings, { prefs, setPrefs, onClose: () => setShowSettings(false) })
      )
    ),

    // audiobook player (hidden when the TTS sidecar is offline / no ready voices)
    status === "ok" && ch && (ch.content || ch.rich_html) && React.createElement(AudioBar, {
      novelId, number, ch, user, onUserUpdate, openReader,
    }),

    // body
    status === "loading" && React.createElement("div", { className: "reader-col", style: colStyle }, React.createElement(Loading, { label: "Loading chapter…" })),

    status === "notfound" && React.createElement("div", { className: "reader-col", style: colStyle },
      React.createElement(EmptyState, { icon: "x", title: "Chapter not found", body: "It may not have been scraped yet." })),

    status === "error" && React.createElement("div", { className: "reader-col", style: colStyle },
      React.createElement(EmptyState, { icon: "x", title: "Couldn't load this chapter" })),

    status === "ok" && ch && React.createElement("div", { className: "reader-col", style: colStyle },
      React.createElement("h1", { className: "reader-title" }, ch.title || `Chapter ${ch.number}`),
      React.createElement("div", { className: "reader-chapnum mono" }, `Chapter ${ch.number}`),
      (ch.overlay || ch.overlay_conflict) && React.createElement("button", {
        className: "tt-chip" + (ch.overlay_conflict ? " conflict" : ""),
        onClick: e => { e.stopPropagation(); setShowTools(true); },
      }, React.createElement(Icon, { name: ch.overlay_conflict ? "alert" : "edit", size: 13 }),
         ch.overlay_conflict ? "Update available" : "Your translation"),
      (!ch.content && !ch.rich_html)
        ? React.createElement("div", { className: "reader-raw-note card" },
            React.createElement(Icon, { name: "x", size: 18, className: "muted" }),
            React.createElement("div", { className: "grow" },
              React.createElement("b", null, ch.translation_status === "failed" ? "Translation failed" : "No text available"),
              React.createElement("p", { className: "muted", style: { margin: "4px 0 10px", fontSize: 14 } },
                ch.translation_status === "failed"
                  ? `Couldn't translate this raw chapter (${ch.language || "foreign"}). Try again.`
                  : "This chapter has no readable text yet."),
              React.createElement("button", { className: "btn btn-ghost", onClick: () => setReloadKey(k => k + 1) },
                React.createElement(Icon, { name: "refresh", size: 15 }), "Retry")))
        : ch.rich_html
          // Imported chapters ship sanitized rich HTML (server-side nh3) — render it directly.
          ? React.createElement("div", { className: "reader-text reader-rich", dangerouslySetInnerHTML: { __html: ch.rich_html } })
          : React.createElement("div", { className: "reader-text" },
              (ch.content || "").split(/\n{2,}/).map((para, i) =>
                React.createElement("p", { key: i }, para)))
    ),

    // floating nav (tap the page to show/hide)
    status === "ok" && ch && React.createElement("div", { className: "reader-float" + (chrome ? "" : " hidden") },
      React.createElement("button", { className: "rf-btn", disabled: ch.prev == null, onClick: () => ch.prev != null && openReader(ch.prev), title: "Previous chapter" },
        React.createElement(Icon, { name: "arrowLeft", size: 18 })),
      React.createElement("button", { className: "rf-btn rf-mid", onClick: backToNovel, title: "Contents" },
        React.createElement(Icon, { name: "layers", size: 17 }), "Contents"),
      React.createElement("button", { className: "rf-btn", disabled: ch.next == null, onClick: () => ch.next != null && openReader(ch.next), title: "Next chapter" },
        React.createElement(Icon, { name: "arrowRight", size: 18 }))
    ),

    // TOC drawer
    showToc && React.createElement("div", { className: "drawer-scrim", onClick: () => setShowToc(false) },
      React.createElement("div", { className: "drawer", onClick: e => e.stopPropagation() },
        React.createElement("div", { className: "drawer-head" },
          React.createElement("b", null, "Contents"),
          React.createElement("button", { className: "icon-btn", onClick: () => setShowToc(false) }, React.createElement(Icon, { name: "x", size: 16 }))),
        toc == null
          ? React.createElement(Loading, { label: "Loading…" })
          : React.createElement("div", { className: "drawer-toc" },
              React.createElement(VolumeTOC, {
                toc, currentNumber: Number(number),
                onOpen: (n) => { setShowToc(false); openReader(n); },
              }))
      )
    )
  );
}

window.Reader = Reader;
