/* ============================================================
   Batch 9 — product operations + reader MVP (frontend)

   Self-contained surfaces layered on the new backend endpoints:
     • ContinueHome   — the first screen after login (resume + active work + newest)
     • JobsPage       — one job center over generic + import + TTS jobs (/activity)
     • NovelHealthPanel — operator pipeline health for a novel
     • RecapPanel     — spoiler-safe "story so far", bounded by the trusted ceiling
     • CostConfirm    — pre-action confirmation showing estimated units vs quota
     • ProvenanceBadges — how a novel/chapter's text was produced

   Everything uses React.createElement (no build step) and the globals exported by
   components.jsx (Icon, Loading, EmptyState, useDebounce, useState/useEffect/…).
   ============================================================ */
// Wrapped in an IIFE so this file's top-level `h`/helpers don't collide with other
// babel scripts' globals; the public components are exported onto `window` at the end.
(function () {
const h = React.createElement;

/* ── Provenance badges ─────────────────────────────────────────────────── */
const PROVENANCE_LABELS = {
  scraped:       { label: "Scraped",   title: "Chapters pulled from a web source" },
  imported:      { label: "Imported",  title: "Ingested from an uploaded EPUB/PDF" },
  ocr:           { label: "OCR'd",     title: "Text recovered from a scanned document" },
  translated:    { label: "Translated", title: "Machine-translated from a raw source" },
  user_edited:   { label: "Edited",    title: "The text has reader/owner edits" },
  owner_approved:{ label: "Owner-approved", title: "A contributed translation was accepted" },
};
const PROVENANCE_ORDER = ["scraped", "imported", "ocr", "translated", "user_edited", "owner_approved"];

function ProvenanceBadges({ provenance, className }) {
  if (!provenance) return null;
  const on = PROVENANCE_ORDER.filter(k => provenance[k]);
  if (on.length === 0) return null;
  return h("div", { className: "prov-badges " + (className || "") },
    on.map(k => h("span", { key: k, className: "chip prov-chip", title: PROVENANCE_LABELS[k].title },
      PROVENANCE_LABELS[k].label))
  );
}

/* ── Cost confirmation before an expensive action ──────────────────────── */
const COST_KIND_LABEL = {
  codex_builds: "codex build", translated_chapters: "chapters", tts_chapters: "chapters", ocr_pages: "pages",
};
function CostConfirm({ novelId, action, params, title, actionLabel = "Confirm", onConfirm, onCancel }) {
  const [est, setEst] = useState(null);   // null = loading, false = error
  const [busy, setBusy] = useState(false);
  const paramsKey = JSON.stringify(params || {});

  useEffect(() => {
    let cancel = false;
    setEst(null);
    window.API.costEstimate(novelId, action, params || {})
      .then(e => { if (!cancel) setEst(e); })
      .catch(() => { if (!cancel) setEst(false); });
    return () => { cancel = true; };
  }, [novelId, action, paramsKey]);

  const units = est && est.estimated_units;
  const unit = est ? (COST_KIND_LABEL[est.quota_kind] || "units") : "";
  const over = est && !est.unlimited && !est.allowed;
  const nothing = est && est.estimated_units === 0;

  async function go() {
    setBusy(true);
    try { await onConfirm(); }
    finally { setBusy(false); }
  }

  const bodyLines = est === null
    ? [h("p", { key: "l", className: "muted", style: { margin: 0 } }, "Estimating cost…")]
    : est === false
      ? [h("p", { key: "e", className: "muted", style: { margin: 0 } }, "Couldn't estimate the cost. You can still proceed.")]
      : [
          h("div", { key: "u", className: "cost-figure" },
            h("b", { className: "cost-num" }, nothing ? "0" : `~${units}`),
            h("span", { className: "muted" }, ` ${unit}`),
            nothing && h("span", { className: "muted", style: { marginLeft: 8 } }, "— nothing new to do")
          ),
          h("div", { key: "q", className: "cost-quota muted" },
            est.unlimited
              ? "Your account has unlimited usage."
              : `Quota this month: ${est.remaining}/${est.limit} ${unit} remaining.`),
          over && h("div", { key: "o", className: "cost-warn" },
            h(Icon, { name: "alert", size: 14 }),
            est.spend_allowed
              ? " This exceeds your remaining quota — it may stop partway."
              : " Verify your email to use this feature."),
        ];

  const canGo = est === false || (est != null && !(over && !est.spend_allowed));
  return h("div", {
    className: "modal-scrim",
    onClick: e => { if (e.target === e.currentTarget && !busy) onCancel(); },
  },
    h("div", { className: "card modal-card", role: "dialog", "aria-modal": "true" },
      h("div", { className: "row", style: { gap: 10, alignItems: "center", marginBottom: 10 } },
        h("span", { className: "cost-icon" }, h(Icon, { name: "sparkles", size: 18 })),
        h("h3", { className: "serif", style: { margin: 0, fontSize: 19 } }, title || "Confirm")
      ),
      h("div", { className: "cost-body" }, bodyLines),
      h("div", { className: "row", style: { gap: 10, marginTop: 18, justifyContent: "flex-end" } },
        h("button", { className: "btn btn-ghost", onClick: onCancel, disabled: busy }, "Cancel"),
        h("button", { className: "btn btn-primary", onClick: go, disabled: busy || !canGo },
          busy ? "Starting…" : actionLabel)
      )
    )
  );
}

/* ── Activity feed rendering (shared by home + job center) ──────────────── */
const ACT_KIND_LABEL = {
  scrape: "Scrape", codex_build: "Codex build", translate: "Translation",
  import: "Import", tts: "Narration",
};
const ACT_STATUS_CHIP = {
  queued: "chip", running: "chip job-run", generating: "chip job-run",
  parsing: "chip job-run", committing: "chip job-run", receiving: "chip job-run",
  ocr_pending: "chip job-run", done: "chip job-ok", committed: "chip job-ok",
  failed: "chip job-err", canceled: "chip",
  awaiting_review: "chip job-warn", awaiting_ocr_confirm: "chip job-warn", ocr_paused: "chip job-warn",
};

function activityProgress(job) {
  const p = job.progress || {};
  if (job.source === "tts") {
    if (p.total != null) return `${p.done || 0}/${p.total} narrated${p.current_chapter != null ? ` — ch. ${p.current_chapter}` : ""}`;
    return job.stage || "narrating…";
  }
  if (job.source === "import") return job.stage || job.status;
  if (job.kind === "translate" && p.total != null) {
    let s = `${p.done || 0}/${p.total} translated`;
    if (p.failed) s += `, ${p.failed} failed`;
    if (p.stopped_reason === "quota") s += " — stopped (quota)";
    return s;
  }
  if (job.kind === "codex_build" && p.steps != null) return `step ${p.step || 0}/${p.steps}${p.stage ? ` — ${p.stage}` : ""}`;
  if (job.kind === "scrape" && p.scraped != null) return `${p.scraped} chapters scraped`;
  return job.stage || "";
}

function ActivityRow({ job, onCancel, onOpenNovel, busyId }) {
  const kindLabel = ACT_KIND_LABEL[job.kind] || job.kind;
  const rowKey = `${job.source}:${job.id}`;
  return h("div", { className: "toc-row activity-row", style: { cursor: "default", alignItems: "center" } },
    h("span", { className: "chip", style: { minWidth: 92 } }, kindLabel),
    h("span", { className: ACT_STATUS_CHIP[job.status] || "chip" }, job.status),
    h("span", { className: "toc-title", style: { flex: 1 } },
      activityProgress(job) || (job.filename ? job.filename : "")),
    job.error && job.status === "failed"
      ? h("span", { className: "muted activity-err", title: job.error }, (job.error || "").slice(0, 60)) : null,
    job.novel_id && onOpenNovel
      ? h("button", { className: "icon-btn", title: "Open novel", onClick: () => onOpenNovel(job.novel_id) },
          h(Icon, { name: "book", size: 15 })) : null,
    job.cancelable && onCancel
      ? h("button", { className: "icon-btn", title: "Cancel", disabled: busyId === rowKey, onClick: () => onCancel(job) },
          h(Icon, { name: "x", size: 15 })) : null
  );
}

/* Small polling hook: refetch while any job is active, back off when idle. */
function usePolledActivity(status) {
  const [jobs, setJobs] = useState(null);
  const timer = React.useRef(null);
  const load = useCallback(async () => {
    try { const r = await window.API.activity(status, 100); setJobs(r.jobs || []); return r.jobs || []; }
    catch (e) { setJobs([]); return []; }
  }, [status]);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const list = await load();
      if (!alive) return;
      const active = list.some(j => j.cancelable);
      timer.current = setTimeout(tick, active ? 3500 : 15000);
    };
    tick();
    return () => { alive = false; if (timer.current) clearTimeout(timer.current); };
  }, [load]);
  return [jobs, load];
}

/* ── Global job center (all durable work for the user) ─────────────────── */
function JobsPage({ openNovel, openLibrary }) {
  const [tab, setTab] = useState("active");   // active | all
  const [jobs, reload] = usePolledActivity(tab);
  const [busyId, setBusyId] = useState(null);

  const cancel = async (job) => {
    const rowKey = `${job.source}:${job.id}`;
    setBusyId(rowKey);
    try { await window.API.cancelActivity(job); await reload(); }
    catch (e) { alert(e.message || "Cancel failed."); }
    finally { setBusyId(null); }
  };

  return h("div", { className: "page" },
    h("div", { className: "lib-head" },
      h("div", null,
        h("h1", { className: "lib-title" }, "Jobs"),
        h("p", { className: "muted", style: { margin: "4px 0 0" } }, "Everything running in the background — scrapes, imports, codex, translation, narration.")
      ),
      h("div", { className: "row", style: { gap: 8 } },
        openLibrary && h("button", { className: "btn btn-ghost", onClick: openLibrary },
          h(Icon, { name: "arrowLeft", size: 16 }), "Home"))
    ),
    h("div", { className: "lib-tabs" },
      [["active", "Active"], ["all", "All"]].map(([id, label]) =>
        h("button", { key: id, className: "lib-tab" + (tab === id ? " active" : ""), onClick: () => setTab(id) }, label))
    ),
    jobs == null
      ? h(Loading, { label: "Loading jobs…" })
      : jobs.length === 0
        ? h(EmptyState, { icon: "sparkles", title: tab === "active" ? "No active jobs" : "No jobs yet",
                          body: "Background work you start (scrape, import, codex, translation, narration) shows up here." })
        : h("div", { className: "card", style: { padding: 12 } },
            jobs.map(job => h(ActivityRow, { key: `${job.source}:${job.id}`, job, onCancel: cancel,
                                             onOpenNovel: openNovel, busyId })))
  );
}

function voiceLabel(id, catalog) {
  const v = catalog && catalog.get(id);
  return (v && (v.name || v.id)) || id;
}

/* ── Novel health panel (operator surface, inside NovelDetail) ─────────── */
function NovelHealthPanel({ novelId, voiceId, ttsVoices }) {
  const [hp, setHp] = useState(null);   // null = loading, false = error
  useEffect(() => {
    let cancel = false;
    setHp(null);
    window.API.novelHealth(novelId, voiceId).then(r => { if (!cancel) setHp(r); }).catch(() => { if (!cancel) setHp(false); });
    return () => { cancel = true; };
  }, [novelId, voiceId]);

  if (hp === false) return null;

  const item = (label, value, tone) =>
    h("div", { className: "health-item" },
      h("div", { className: "health-num" + (tone ? " " + tone : "") }, value),
      h("div", { className: "health-label" }, label));
  const catalog = new Map((ttsVoices || []).map(v => [v.id, v]));
  const prose = hp && hp.audio ? (hp.audio.prose_chapters || 0) : 0;
  const voiceRows = [];
  if (hp && hp.audio) {
    const byVoice = new Map();
    (ttsVoices || []).filter(v => v.ready !== false).forEach(v => {
      byVoice.set(v.id, { voice_id: v.id, have: 0, missing: prose, catalog: v });
    });
    (hp.audio.voices || []).forEach(v => {
      byVoice.set(v.voice_id, { ...byVoice.get(v.voice_id), ...v });
    });
    byVoice.forEach(v => voiceRows.push(v));
    voiceRows.sort((a, b) => voiceLabel(a.voice_id, catalog).localeCompare(voiceLabel(b.voice_id, catalog)));
  }

  return h(React.Fragment, null,
    h("p", { className: "section-eyebrow", style: { marginTop: 28 } }, "Health"),
    hp == null
      ? h("div", { className: "card", style: { padding: 16 } }, h("span", { className: "muted" }, "Checking pipeline health…"))
      : h("div", { className: "card", style: { padding: 16 } },
          h("div", { className: "health-grid" },
            item("Codex entities", hp.codex.entities,
                 hp.codex.missing ? "warn" : (hp.codex.stale ? "warn" : "ok")),
            item("Untranslated raw", hp.untranslated_raw_chapters, hp.untranslated_raw_chapters > 0 ? "warn" : "ok"),
            hp.audio && hp.audio.missing != null
              ? item("Missing audio (any voice)", hp.audio.missing, hp.audio.missing > 0 ? "warn" : "ok")
              : item("Audio", "—"),
            item("Chapters", hp.total_chapters)
          ),
          voiceRows.length > 0 && h("div", { className: "health-voices" },
            voiceRows.map(v => {
              const have = v.have || 0;
              const pct = prose ? Math.round((have / prose) * 100) : 0;
              const meta = [v.catalog && v.catalog.language, v.catalog && v.catalog.gender, v.catalog && v.catalog.accent].filter(Boolean).join(" · ");
              return h("div", { key: v.voice_id, className: "health-voice-row" },
                h("div", { className: "health-voice-head" },
                  h("span", null, voiceLabel(v.voice_id, catalog)),
                  h("span", { className: "mono muted" }, `${have}/${prose}`)),
                h("div", { className: "health-voice-bar" }, h("div", { style: { width: pct + "%" } })),
                meta && h("div", { className: "health-voice-meta muted" }, meta)
              );
            })
          ),
	          h("div", { className: "health-notes muted" },
            hp.codex.missing ? h("div", null, "• Codex is enabled but empty — build it from the pipeline.") : null,
            (!hp.codex.missing && hp.codex.stale) ? h("div", null,
              `• Codex covers up to ch. ${hp.codex.coverage_chapter} of ${hp.book_max_chapter} — rebuild to catch up.`) : null,
            hp.source_last_scraped ? h("div", null, `• Source last scraped ${new Date(hp.source_last_scraped).toLocaleString()}.`) : null,
            (hp.recent_errors || []).slice(0, 3).map((e, i) =>
              h("div", { key: i, className: "health-err", title: e.error }, `• ${e.kind} error: ${(e.error || "").slice(0, 80)}`))
          )
        )
  );
}

/* ── No-spoiler recap panel (in the Ask surface / codex) ───────────────── */
function RecapPanel({ novelId, ceiling }) {
  const [state, setState] = useState({ status: "idle" });   // idle|loading|ready|error

  async function run() {
    setState({ status: "loading" });
    try {
      const r = await window.API.recap(novelId, ceiling);
      setState({ status: "ready", data: r });
    } catch (e) {
      setState({ status: "error", message: e.message || "Recap failed." });
    }
  }

  const d = state.data;
  return h("div", { className: "card recap-card" },
    h("div", { className: "row", style: { gap: 10, alignItems: "center" } },
      h("span", { className: "hero-eyebrow", style: { color: "var(--sage)", margin: 0 } },
        h(Icon, { name: "book", size: 14 }), "Story so far"),
      h("span", { className: "muted", style: { fontSize: 12.5, marginLeft: "auto" } },
        `Spoiler-safe · up to ch. ${ceiling}`)
    ),
    state.status === "idle" && h("p", { className: "muted", style: { fontSize: 13.6, lineHeight: 1.55 } },
      "Get a concise recap of everything up to your current chapter — nothing past it."),
    state.status === "error" && h("p", { className: "muted", style: { color: "var(--rose, crimson)", fontSize: 13.5 } }, state.message),
    state.status === "ready" && d && h(React.Fragment, null,
      h("div", { className: "recap-body" }, h(AnswerBody, { answer: d.answer || "", citeMap: window.buildCiteMap(d.citations) })),
      d.ceiling_clamped
        ? h("p", { className: "muted", style: { fontSize: 12.5, marginTop: 6 } },
            `Bounded to chapter ${d.effective_ceiling} (your trusted progress).`)
        : null
    ),
    h("div", { className: "row", style: { marginTop: 12 } },
      h("button", { className: "btn btn-primary", onClick: run, disabled: state.status === "loading" },
        h(Icon, { name: "sparkles", size: 16 }),
        state.status === "loading" ? "Building recap…" : (state.status === "ready" ? "Refresh recap" : "Recap the story so far"))
    )
  );
}

/* ── Unified "Continue" home (first screen after login) ─────────────────── */
function ContinueMiniCard({ n, openNovel, openReader, listening }) {
  const pct = n.pct_read || 0;
  const resumeCh = n.last_chapter != null ? n.last_chapter : 1;
  return h("div", { className: "cont-card", role: "button", tabIndex: 0,
      onClick: () => openNovel(n.id),
      onKeyDown: e => { if (e.key === "Enter") openNovel(n.id); } },
    h("div", { className: "cont-cover" },
      n.cover_url ? h("img", { src: n.cover_url, alt: "", loading: "lazy" })
        : h("div", { className: "novel-cover-ph" }, h(Icon, { name: "book", size: 24 }))
    ),
    h("div", { className: "cont-body" },
      h("div", { className: "cont-title" }, n.title),
      h("div", { className: "progress-track", style: { marginTop: 8 } },
        h("div", { className: "progress-fill", style: { width: pct + "%" } })),
      h("div", { className: "cont-foot" },
        h("span", { className: "muted" }, `Ch. ${resumeCh}${n.max_chapter ? ` / ${n.max_chapter}` : ""}`),
        h("button", { className: "btn btn-primary cont-resume", onClick: e => { e.stopPropagation(); openReader(n.id, resumeCh); } },
          h(Icon, { name: listening ? "headphones" : "book", size: 14 }), listening ? "Listen" : "Resume")
      )
    )
  );
}

function ContinueHome({ user, openNovel, openReader, openImport, openDiscover, openLibrary, openJobs }) {
  const [data, setData] = useState(null);   // null = loading
  const load = useCallback(() => {
    window.API.home().then(setData).catch(() => setData({ continue_reading: [], continue_listening: [], active_jobs: [], recent_imports: [], newest: [] }));
  }, []);
  useEffect(() => { load(); }, [load]);

  const openReaderAt = (id, ch) => openReader(id, ch);
  const name = (user && (user.display_name || user.username)) || "reader";

  if (data == null) return h("div", { className: "page" }, h(Loading, { label: "Loading your home…" }));

  const cr = data.continue_reading || [];
  const cl = data.continue_listening || [];
  const jobs = data.active_jobs || [];
  const imports = data.recent_imports || [];
  const newest = data.newest || [];
  const empty = cr.length === 0 && jobs.length === 0 && imports.length === 0 && newest.length === 0;

  const section = (title, right, body) => h("section", { className: "home-section" },
    h("div", { className: "row", style: { alignItems: "baseline", marginBottom: 10 } },
      h("p", { className: "section-eyebrow", style: { margin: 0 } }, title),
      right ? h("div", { style: { marginLeft: "auto" } }, right) : null),
    body);

  return h("div", { className: "page" },
    h("div", { className: "lib-head" },
      h("div", null,
        h("h1", { className: "lib-title" }, `Welcome back, ${name}`),
        h("p", { className: "muted", style: { margin: "4px 0 0" } }, "Pick up where you left off, and keep an eye on what's running.")
      ),
      h("div", { className: "row", style: { gap: 8, flexWrap: "wrap" } },
        h("button", { className: "btn btn-ghost", onClick: openLibrary }, h(Icon, { name: "book", size: 16 }), "Library"),
        openDiscover && h("button", { className: "btn btn-ghost", onClick: openDiscover }, h(Icon, { name: "compass", size: 16 }), "Discover"),
        openImport && h("button", { className: "btn btn-ghost", onClick: openImport }, h(Icon, { name: "book", size: 16 }), "Import"),
        openJobs && h("button", { className: "btn btn-ghost", onClick: openJobs }, h(Icon, { name: "sparkles", size: 16 }), "Jobs"))
    ),

    empty && h(EmptyState, { icon: "book", title: "Nothing here yet",
      body: "Add a novel or open one from Discover to start reading — your progress and active jobs will show up here." }),

    cr.length > 0 && section("Continue reading", null,
      h("div", { className: "cont-grid" }, cr.map(n => h(ContinueMiniCard, { key: n.id, n, openNovel, openReader: openReaderAt })))),

    cl.length > 0 && section("Continue listening", null,
      h("div", { className: "cont-grid" }, cl.map(n => h(ContinueMiniCard, { key: "l" + n.id, n, openNovel, openReader: openReaderAt, listening: true })))),

    jobs.length > 0 && section("Active jobs",
      openJobs && h("button", { className: "linkish", onClick: openJobs }, "View all"),
      h("div", { className: "card", style: { padding: 12 } },
        jobs.map(job => h(ActivityRow, { key: `${job.source}:${job.id}`, job, onOpenNovel: openNovel })))),

    imports.length > 0 && section("Recent imports",
      openImport && h("button", { className: "linkish", onClick: openImport }, "Open importer"),
      h("div", { className: "card", style: { padding: 12 } },
        imports.map(j => h("div", { key: j.id, className: "toc-row", style: { cursor: "default", alignItems: "center" } },
          h("span", { className: ACT_STATUS_CHIP[j.status] || "chip" }, j.status),
          h("span", { className: "toc-title", style: { flex: 1 } }, j.filename || j.stage || `Import #${j.id}`),
          j.novel_id ? h("button", { className: "icon-btn", title: "Open novel", onClick: () => openNovel(j.novel_id) },
            h(Icon, { name: "book", size: 15 })) : null)))),

    newest.length > 0 && section("Newest in the shared library",
      openDiscover && h("button", { className: "linkish", onClick: openDiscover }, "Discover more"),
      h("div", { className: "cont-grid" }, newest.map(n => h("div", {
          key: "n" + n.id, className: "cont-card", role: "button", tabIndex: 0,
          onClick: () => openNovel(n.id), onKeyDown: e => { if (e.key === "Enter") openNovel(n.id); } },
        h("div", { className: "cont-cover" },
          n.cover_url ? h("img", { src: n.cover_url, alt: "", loading: "lazy" })
            : h("div", { className: "novel-cover-ph" }, h(Icon, { name: "book", size: 24 }))),
        h("div", { className: "cont-body" },
          h("div", { className: "cont-title" }, n.title),
          h("div", { className: "cont-foot" },
            h("span", { className: "muted" }, `${n.chapter_count} ch.`),
            n.owner_username ? h("span", { className: "muted", style: { marginLeft: "auto" } }, "@" + n.owner_username) : null)))))
    )
  );
}

Object.assign(window, {
  ProvenanceBadges, PROVENANCE_LABELS, CostConfirm, JobsPage, ActivityRow,
  NovelHealthPanel, RecapPanel, ContinueHome, usePolledActivity,
});
})();
