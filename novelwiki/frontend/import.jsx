/* ============================================================
   Import — upload an EPUB, review the auto-detected segmentation plan, then commit it
   into a new (or existing) novel. Heavy work runs in the server-side import worker; this
   view uploads, polls the job for progress, lets the user edit the plan (include/rename/
   kind/number/merge/split), and triggers the commit.
   ============================================================ */
const IMPORT_KINDS = ["chapter", "frontmatter", "interlude", "backmatter"];
// Statuses where the job is still being worked on server-side → keep polling.
const IMPORT_BUSY = ["receiving", "uploaded", "parsing", "segmenting", "committing",
  "ocr_pending", "ocr_running", "ocr_paused"];
const IMPORT_STATUS_LABEL = {
  receiving: "Receiving…", uploaded: "Queued…", parsing: "Parsing…", segmenting: "Segmenting…",
  awaiting_ocr_confirm: "Scanned — needs OCR", ocr_pending: "OCR queued…", ocr_running: "Reading pages…",
  ocr_paused: "OCR paused (budget)", awaiting_review: "Ready to review", committing: "Committing…",
  committed: "Committed", failed: "Failed", canceled: "Canceled",
};

function UploadDrop({ onUploaded }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef(null);

  async function send(file) {
    if (!file || busy) return;
    if (!/\.(epub|pdf)$/i.test(file.name)) { setErr("Only .epub and .pdf files are supported."); return; }
    setBusy(true); setErr(null);
    try { const r = await window.API.uploadImport(file); onUploaded(r.id); }
    catch (e) { setErr(e.message || "Upload failed."); }
    finally { setBusy(false); }
  }

  return React.createElement("div", null,
    React.createElement("div", {
      className: "import-drop" + (drag ? " drag" : ""),
      onClick: () => inputRef.current && inputRef.current.click(),
      onDragOver: e => { e.preventDefault(); setDrag(true); },
      onDragLeave: () => setDrag(false),
      onDrop: e => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files[0]); },
    },
      React.createElement(Icon, { name: "book", size: 26, className: "muted" }),
      React.createElement("div", { className: "import-drop-text" },
        React.createElement("b", null, busy ? "Uploading…" : "Drop an EPUB or PDF here, or click to choose"),
        React.createElement("span", { className: "muted", style: { fontSize: 13 } }, "We parse it (scanned PDFs are OCR'd), you review the chapters, then commit.")
      ),
      React.createElement("input", {
        ref: inputRef, type: "file", accept: ".epub,.pdf", style: { display: "none" },
        onChange: e => send(e.target.files[0]),
      })
    ),
    err && React.createElement("div", { className: "muted", style: { color: "var(--rose, crimson)", fontSize: 13, marginTop: 8 } }, err)
  );
}

function SegmentRow({ seg, onPatch, onMerge, onSplit, canMerge }) {
  const wc = seg.word_count != null ? `${seg.word_count.toLocaleString()} words` : "";
  return React.createElement("div", { className: "seg-row" + (seg.include ? "" : " excluded") },
    React.createElement("label", { className: "seg-include", title: seg.include ? "Included" : "Excluded" },
      React.createElement("input", { type: "checkbox", checked: !!seg.include, onChange: e => onPatch({ include: e.target.checked }) })
    ),
    React.createElement("div", { className: "seg-main" },
      React.createElement("div", { className: "seg-line1" },
        React.createElement("input", {
          className: "seg-title", value: seg.title || "",
          onChange: e => onPatch({ title: e.target.value }), placeholder: "Untitled",
        }),
        React.createElement("select", {
          className: "seg-kind", value: seg.kind, onChange: e => onPatch({ kind: e.target.value }),
        }, IMPORT_KINDS.map(k => React.createElement("option", { key: k, value: k }, k))),
        React.createElement("input", {
          className: "seg-num", value: seg.number == null ? "" : seg.number, placeholder: "#",
          title: "Chapter number", inputMode: "decimal",
          onChange: e => { const v = e.target.value.trim(); onPatch({ number: v === "" ? null : parseFloat(v) }); },
        })
      ),
      React.createElement("div", { className: "seg-line2 muted" },
        seg.part_label && React.createElement("span", { className: "chip", style: { marginRight: 6 } }, seg.part_label),
        React.createElement("span", { className: "mono", style: { marginRight: 8 } }, `[${seg.block_range[0]}–${seg.block_range[1]}]`),
        wc && React.createElement("span", { style: { marginRight: 8 } }, wc),
        seg.first_line && React.createElement("span", { className: "seg-first" }, seg.first_line)
      )
    ),
    React.createElement("div", { className: "seg-actions" },
      React.createElement("button", { className: "icon-btn", title: "Merge into previous", disabled: !canMerge, onClick: onMerge },
        React.createElement(Icon, { name: "merge", size: 15 })),
      React.createElement("button", { className: "icon-btn", title: "Split in half", onClick: onSplit },
        React.createElement(Icon, { name: "scissors", size: 15 }))
    )
  );
}

function PlanEditor({ job, plan, setPlan, onCommit, busy }) {
  const segs = plan.segments || [];
  const novels = job._novels || [];
  const [mode, setMode] = useState("new");
  const [novelId, setNovelId] = useState("");
  const [offset, setOffset] = useState("0");

  const patchSeg = (i, body) => setPlan(p => {
    const next = { ...p, segments: p.segments.map((s, j) => j === i ? { ...s, ...body } : s) };
    return next;
  });
  const mergePrev = (i) => setPlan(p => {
    if (i <= 0) return p;
    const segments = p.segments.slice();
    const prev = segments[i - 1], cur = segments[i];
    segments[i - 1] = { ...prev, block_range: [prev.block_range[0], cur.block_range[1]],
      word_count: (prev.word_count || 0) + (cur.word_count || 0) };
    segments.splice(i, 1);
    return { ...p, segments };
  });
  const splitHalf = (i) => setPlan(p => {
    const segments = p.segments.slice();
    const s = segments[i];
    const [a, b] = s.block_range;
    if (b <= a) return p;
    const mid = Math.floor((a + b) / 2);
    segments.splice(i, 1,
      { ...s, block_range: [a, mid] },
      { ...s, id: s.id + "b", title: s.title + " (cont.)", block_range: [mid + 1, b], number: null });
    return { ...p, segments };
  });

  const includedCount = segs.filter(s => s.include).length;

  return React.createElement("div", { className: "plan-editor" },
    React.createElement("div", { className: "plan-head" },
      React.createElement("div", null,
        React.createElement("b", null, `${segs.length} segments`),
        React.createElement("span", { className: "muted", style: { marginLeft: 8, fontSize: 13 } }, `${includedCount} will be imported`)
      )
    ),
    React.createElement("div", { className: "seg-list" },
      segs.map((s, i) => React.createElement(SegmentRow, {
        key: s.id + ":" + i, seg: s, canMerge: i > 0,
        onPatch: body => patchSeg(i, body),
        onMerge: () => mergePrev(i), onSplit: () => splitHalf(i),
      }))
    ),
    React.createElement("div", { className: "card commit-bar" },
      React.createElement("div", { className: "rs-seg" },
        React.createElement("button", { className: mode === "new" ? "active" : "", onClick: () => setMode("new") }, "New novel"),
        React.createElement("button", { className: mode === "append" ? "active" : "", onClick: () => setMode("append") }, "Append to…")
      ),
      mode === "append" && React.createElement("select", {
        className: "gl-input", value: novelId, onChange: e => setNovelId(e.target.value), style: { flex: "1 1 160px" },
      },
        React.createElement("option", { value: "" }, "Choose a novel…"),
        novels.map(n => React.createElement("option", { key: n.id, value: n.id }, n.title))
      ),
      mode === "append" && React.createElement("input", {
        className: "gl-input", style: { flex: "0 0 120px" }, value: offset,
        onChange: e => setOffset(e.target.value), placeholder: "offset", inputMode: "decimal", title: "Chapter offset",
      }),
      React.createElement("button", {
        className: "btn btn-primary", disabled: busy || includedCount === 0 || (mode === "append" && !novelId),
        onClick: () => onCommit(mode === "append" ? { mode: "append", novel_id: parseInt(novelId), offset: parseFloat(offset) || 0 } : { mode: "new" }),
      }, React.createElement(Icon, { name: "check", size: 16 }), busy ? "Committing…" : "Commit")
    )
  );
}

function OcrConfirm({ job, onConfirm, busy }) {
  const [geminiFirst, setGeminiFirst] = useState(false);
  const est = job.cost_estimate || {};
  const pages = est.scanned_pages != null ? est.scanned_pages : (job.stats && job.stats.page_count) || 0;
  return React.createElement("div", { className: "card", style: { padding: 16 } },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Scanned PDF — needs OCR"),
    React.createElement("p", { style: { margin: "0 0 8px", fontSize: 14 } },
      `${pages.toLocaleString()} pages look scanned. We'll read them with the local OCR engine and `,
      "escalate hard pages to Gemini vision."),
    est.est_gemini_requests != null && React.createElement("p", { className: "muted", style: { fontSize: 13, margin: "0 0 10px" } },
      `~${est.est_gemini_requests.toLocaleString()} Gemini requests (~${est.est_minutes} min)`,
      est.budget_remaining != null ? ` · ${est.budget_remaining.toLocaleString()} of today's quota left` : ""),
    React.createElement("label", { className: "check", style: { marginBottom: 12 } },
      React.createElement("input", { type: "checkbox", checked: geminiFirst, onChange: e => setGeminiFirst(e.target.checked) }),
      "Use Gemini for every page (skip the local engine — higher quality, more quota)"),
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("button", { className: "btn btn-primary", disabled: busy, onClick: () => onConfirm({ gemini_first: geminiFirst }) },
        React.createElement(Icon, { name: "play", size: 16 }), busy ? "Starting…" : "Run OCR")
    )
  );
}

function OcrProgress({ job }) {
  const p = job.progress || {};
  const pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
  const paused = job.status === "ocr_paused";
  return React.createElement("div", { className: "card", style: { padding: 16 } },
    React.createElement("div", { className: "row", style: { gap: 8, marginBottom: 10 } },
      React.createElement(Icon, { name: paused ? "pause" : "cpu", size: 16, className: "muted" }),
      React.createElement("b", { className: "grow" }, IMPORT_STATUS_LABEL[job.status] || "Reading pages…"),
      p.total ? React.createElement("span", { className: "mono muted", style: { fontSize: 13 } }, `${p.done}/${p.total}`) : null
    ),
    React.createElement("div", { className: "progress-track" },
      React.createElement("div", { className: "progress-fill", style: { width: pct + "%" } })),
    paused && React.createElement("p", { className: "muted", style: { fontSize: 12.5, marginTop: 8, marginBottom: 0 } },
      "Gemini's daily free quota is used up. This resumes automatically tomorrow — no pages are re-read.")
  );
}

function ImportView({ openNovel, openLibrary }) {
  const [jobs, setJobs] = useState(null);
  const [sel, setSel] = useState(null);        // selected job id
  const [job, setJob] = useState(null);        // selected job detail
  const [plan, setPlan] = useState(null);      // local editable copy of the plan
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const novelsRef = useRef([]);

  const loadJobs = useCallback(() => {
    window.API.importJobs().then(setJobs).catch(() => setJobs([]));
  }, []);
  useEffect(() => {
    loadJobs();
    window.API.novels().then(n => { novelsRef.current = n; }).catch(() => {});
  }, [loadJobs]);

  // Load + poll the selected job while it's being worked on server-side.
  useEffect(() => {
    if (sel == null) { setJob(null); setPlan(null); return; }
    let cancel = false, timer = null;
    const tick = () => {
      window.API.importJob(sel).then(j => {
        if (cancel) return;
        j._novels = novelsRef.current;
        setJob(j);
        setPlan(prev => {
          // Adopt the server plan once (on first load / after a re-parse); keep local edits otherwise.
          if (j.plan && (!prev || prev._forJob !== j.id || j.status === "committed")) {
            return { ...j.plan, _forJob: j.id };
          }
          return prev;
        });
        if (IMPORT_BUSY.includes(j.status)) timer = setTimeout(tick, 1500);
        else loadJobs();
      }).catch(() => {});
    };
    tick();
    return () => { cancel = true; if (timer) clearTimeout(timer); };
  }, [sel, loadJobs]);

  async function onUploaded(jobId) { setMsg(null); loadJobs(); setSel(jobId); }

  async function commit(body) {
    setBusy(true); setMsg(null);
    try {
      if (plan) await window.API.updateImportPlan(sel, { version: plan.version || 1, segments: plan.segments });
      await window.API.commitImport(sel, body);
      setMsg("Commit started…");
    } catch (e) { setMsg(e.message || "Commit failed."); }
    finally { setBusy(false); }
  }

  async function confirmOcr(body) {
    setBusy(true); setMsg(null);
    try { await window.API.confirmOcr(sel, body); setMsg("OCR started…"); }
    catch (e) { setMsg(e.message || "Could not start OCR."); }
    finally { setBusy(false); }
  }

  async function removeJob(jid) {
    await window.API.deleteImport(jid).catch(() => {});
    if (sel === jid) { setSel(null); }
    loadJobs();
  }

  const meta = (job && job.detected_meta) || {};
  const committedNovel = job && job.status === "committed" && job.novel_id;

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "lib-head" },
      React.createElement("div", null,
        React.createElement("h1", { className: "lib-title" }, "Import a book"),
        React.createElement("p", { className: "muted", style: { margin: "4px 0 0" } }, "Bring an EPUB or PDF into your library — chapters, cover and illustrations. Scanned PDFs are OCR'd.")
      ),
      React.createElement("button", { className: "btn btn-ghost", onClick: openLibrary },
        React.createElement(Icon, { name: "arrowLeft", size: 16 }), "Library")
    ),

    React.createElement(UploadDrop, { onUploaded }),
    msg && React.createElement("div", { className: "card", style: { padding: "10px 16px", margin: "12px 0", fontSize: 13.5 } }, msg),

    React.createElement("div", { className: "import-cols" },
      // Jobs list
      React.createElement("div", { className: "import-jobs" },
        React.createElement("p", { className: "section-eyebrow" }, "Recent imports"),
        jobs == null
          ? React.createElement(Loading, { label: "Loading…" })
          : jobs.length === 0
            ? React.createElement("div", { className: "muted", style: { fontSize: 13, padding: 8 } }, "No imports yet.")
            : React.createElement("div", { className: "card", style: { padding: 6 } },
                jobs.map(j => React.createElement("div", {
                  key: j.id, className: "import-job-row" + (sel === j.id ? " active" : ""),
                  onClick: () => setSel(j.id),
                },
                  React.createElement("div", { className: "grow" },
                    React.createElement("div", { style: { fontWeight: 600, fontSize: 13.5 } }, (j.detected_meta && j.detected_meta.title) || j.filename || `Job ${j.id}`),
                    React.createElement("div", { className: "muted", style: { fontSize: 12 } }, IMPORT_STATUS_LABEL[j.status] || j.status)
                  ),
                  React.createElement("button", { className: "icon-btn", title: "Delete", onClick: e => { e.stopPropagation(); removeJob(j.id); } },
                    React.createElement(Icon, { name: "x", size: 14 }))
                ))
              )
      ),

      // Selected job detail
      React.createElement("div", { className: "import-detail" },
        job == null
          ? React.createElement(EmptyState, { icon: "book", title: "Select an import", body: "Upload an EPUB or pick a recent import to review it." })
          : React.createElement(React.Fragment, null,
              React.createElement("div", { className: "import-meta card" },
                meta.cover_url && React.createElement("img", { className: "import-cover", src: meta.cover_url, alt: "" }),
                React.createElement("div", { className: "grow" },
                  React.createElement("b", null, meta.title || job.filename || "Untitled"),
                  meta.author && React.createElement("div", { className: "muted", style: { fontSize: 13 } }, meta.author),
                  React.createElement("div", { className: "muted", style: { fontSize: 12.5, marginTop: 4 } },
                    `${IMPORT_STATUS_LABEL[job.status] || job.status}${job.stage ? " · " + job.stage : ""}`),
                  job.stats && job.stats.images != null && React.createElement("div", { className: "muted", style: { fontSize: 12.5 } },
                    `${job.stats.segments || 0} segments · ${job.stats.images || 0} images`)
                )
              ),
              job.error && React.createElement("div", { className: "card", style: { padding: "10px 14px", color: "var(--danger, #c0392b)", fontSize: 13 } }, job.error),

              committedNovel && React.createElement("div", { className: "card", style: { padding: 14, display: "flex", gap: 10, alignItems: "center" } },
                React.createElement(Icon, { name: "check", size: 18, className: "muted" }),
                React.createElement("b", { className: "grow" }, "Imported into your library."),
                React.createElement("button", { className: "btn btn-primary", onClick: () => openNovel(job.novel_id) }, "Open novel")),

              job.status === "awaiting_ocr_confirm"
                ? React.createElement(OcrConfirm, { job, onConfirm: confirmOcr, busy })
                : ["ocr_pending", "ocr_running", "ocr_paused"].includes(job.status)
                  ? React.createElement(OcrProgress, { job })
                  : job.status === "awaiting_review" && plan
                    ? React.createElement(PlanEditor, { job, plan, setPlan, onCommit: commit, busy })
                    : IMPORT_BUSY.includes(job.status)
                      ? React.createElement(Loading, { label: IMPORT_STATUS_LABEL[job.status] || "Working…" })
                      : null
            )
      )
    )
  );
}

window.ImportView = ImportView;
