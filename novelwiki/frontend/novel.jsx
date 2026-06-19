/* ============================================================
   Novel detail — the per-novel hub: continue reading, sources, scraping,
   codex build, and the table of contents.
   ============================================================ */

// Non-chapter sections from file imports get a short tag instead of a number.
const TOC_KIND_LABEL = { frontmatter: "front", interlude: "interlude", backmatter: "extra" };

// Build the TOC as a flat element list, inserting a heading whenever the imported
// `part_label` (e.g. "Volume 1") changes and tagging non-chapter sections.
function buildToc(toc, progress, openReader) {
  const out = [];
  let lastPart;
  toc.forEach(ch => {
    if (ch.part_label && ch.part_label !== lastPart) {
      out.push(React.createElement("div", { key: "part:" + ch.part_label, className: "toc-part" }, ch.part_label));
    }
    lastPart = ch.part_label || lastPart;
    const isSection = ch.kind && ch.kind !== "chapter";
    out.push(React.createElement("button", {
      key: ch.number,
      className: "toc-row" + (progress.last_chapter === ch.number ? " current" : "") + (isSection ? " toc-section" : ""),
      onClick: () => openReader(ch.number),
    },
      React.createElement("span", { className: "toc-num mono" }, isSection ? "—" : ch.number),
      React.createElement("span", { className: "toc-title" }, ch.title || `Chapter ${ch.number}`),
      isSection ? React.createElement("span", { className: "chip toc-kind", title: "Non-chapter section" }, TOC_KIND_LABEL[ch.kind] || ch.kind) : null,
      (!ch.has_content && ch.translation_status === "pending")
        ? React.createElement("span", { className: "chip", title: "Raw — translates on open" }, "raw") : null,
      React.createElement(Icon, { name: "arrowRight", size: 15, className: "muted" })
    ));
  });
  return out;
}

function AddSourceForm({ novelId, adapters, onAdded, onCancel }) {
  const [adapter, setAdapter] = useState(adapters[0] ? adapters[0].name : "fenrirealm");
  const [startUrl, setStartUrl] = useState("");
  const [language, setLanguage] = useState("en");
  const [isRaw, setIsRaw] = useState(false);
  const [continuesFrom, setContinuesFrom] = useState("");
  const [localStart, setLocalStart] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!startUrl.trim() || busy) return;
    setBusy(true);
    // Calculate custom offset: global_number = local_number + offset
    // => offset = global_start - local_start
    let offset = 0;
    if (continuesFrom.trim()) {
      const glob = parseFloat(continuesFrom);
      const loc = localStart.trim() ? parseFloat(localStart) : 1.0;
      offset = glob - loc;
    }

    try {
      await window.API.addSource(novelId, {
        adapter,
        start_url: startUrl.trim(),
        language,
        is_raw: isRaw,
        chapter_offset: offset,
        config: null,
      });
      onAdded();
    } finally {
      setBusy(false);
    }
  }

  return React.createElement("form", { className: "card add-source", onSubmit: submit },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Add a source"),
    React.createElement("div", { className: "row", style: { gap: 12, flexWrap: "wrap" } },
      React.createElement("label", { className: "field", style: { flex: "1 1 200px" } },
        React.createElement("span", null, "Technique"),
        React.createElement("select", { value: adapter, onChange: e => setAdapter(e.target.value) },
          adapters.map(a => React.createElement("option", { key: a.name, value: a.name }, a.label)))
      ),
      React.createElement("label", { className: "field", style: { flex: "0 0 110px" } },
        React.createElement("span", null, "Language"),
        React.createElement("input", { value: language, onChange: e => setLanguage(e.target.value) })
      )
    ),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "First chapter URL"),
      React.createElement("input", { value: startUrl, onChange: e => setStartUrl(e.target.value), placeholder: "https://…/1" })
    ),
    React.createElement("div", { className: "row", style: { gap: 16, flexWrap: "wrap" } },
      React.createElement("label", { className: "field", style: { flex: "1 1 180px" } },
        React.createElement("span", null, "Continues from global chapter"),
        React.createElement("input", { value: continuesFrom, onChange: e => setContinuesFrom(e.target.value), placeholder: "e.g. 125", inputMode: "decimal" })
      ),
      continuesFrom.trim() && React.createElement("label", { className: "field", style: { flex: "1 1 180px" } },
        React.createElement("span", null, "Source-local starting chapter"),
        React.createElement("input", { value: localStart, onChange: e => setLocalStart(e.target.value), placeholder: "defaults to 1", inputMode: "decimal" })
      ),
      React.createElement("label", { className: "check" },
        React.createElement("input", { type: "checkbox", checked: isRaw, onChange: e => setIsRaw(e.target.checked) }),
        "Raw (needs translation)"
      )
    ),
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy }, busy ? "Adding…" : "Add source"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel")
    )
  );
}

function EditSourceForm({ novelId, source, onSaved, onCancel }) {
  const [offset, setOffset] = useState(String(source.chapter_offset || 0));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      const r = await window.API.updateSource(novelId, source.id, { chapter_offset: parseFloat(offset) || 0 });
      onSaved(r);
    } catch (e) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return React.createElement("div", { className: "card", style: { padding: 12, marginTop: 8, background: "var(--bg-2)" } },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Edit chapter offset"),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Chapter offset (added to this source's own numbers)"),
      React.createElement("input", { value: offset, onChange: e => setOffset(e.target.value), placeholder: "e.g. -1", inputMode: "decimal" })
    ),
    React.createElement("p", { className: "muted", style: { fontSize: 12, marginTop: 6 } },
      "Use -1 if this raw source is one chapter ahead of the translation. Existing chapters are renumbered immediately."),
    err && React.createElement("p", { style: { color: "var(--danger, #c0392b)", fontSize: 12.5, marginTop: 4 } }, err),
    React.createElement("div", { className: "row", style: { gap: 10, marginTop: 8 } },
      React.createElement("button", { className: "btn btn-primary", type: "button", onClick: save, disabled: busy }, busy ? "Saving…" : "Save"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel")
    )
  );
}

function NovelEditForm({ novel, onSaved, onCancel, onRequestDelete }) {
  const [title, setTitle] = useState(novel.title || "");
  const [author, setAuthor] = useState(novel.author || "");
  const [description, setDescription] = useState(novel.description || "");
  const [cover, setCover] = useState(novel.cover_url || "");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      await window.API.updateNovel(novel.id, {
        title: title.trim(), author: author.trim() || null,
        description: description.trim() || null, cover_url: cover.trim() || null,
      });
      onSaved();
    } finally { setBusy(false); }
  }

  return React.createElement("form", { className: "card add-novel", onSubmit: submit, style: { marginBottom: 26 } },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Edit novel"),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Title"),
      React.createElement("input", { value: title, onChange: e => setTitle(e.target.value), autoFocus: true })),
    React.createElement("div", { className: "row", style: { gap: 12, flexWrap: "wrap" } },
      React.createElement("label", { className: "field", style: { flex: "1 1 180px" } },
        React.createElement("span", null, "Author"),
        React.createElement("input", { value: author, onChange: e => setAuthor(e.target.value) })),
      React.createElement("label", { className: "field", style: { flex: "1 1 240px" } },
        React.createElement("span", null, "Cover image URL"),
        React.createElement("input", { value: cover, onChange: e => setCover(e.target.value), placeholder: "https://…" }))),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Description"),
      React.createElement("textarea", { value: description, onChange: e => setDescription(e.target.value), rows: 3 })),
    React.createElement("div", { className: "row", style: { gap: 10, alignItems: "center" } },
      React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy }, busy ? "Saving…" : "Save"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel"),
      React.createElement("div", { className: "grow" }),
      React.createElement("button", {
        className: "btn btn-ghost is-danger", type: "button", onClick: onRequestDelete,
        title: "Permanently delete this novel",
      }, React.createElement(Icon, { name: "trash", size: 16 }), "Delete novel"))
  );
}

function GlossaryEditor({ novelId, glossary, reload }) {
  const [open, setOpen] = useState(false);   // minimized by default; expand on click
  const [st, setSt] = useState("");
  const [tr, setTr] = useState("");
  const [type, setType] = useState("name");
  const [busy, setBusy] = useState(false);

  async function add(e) {
    e.preventDefault();
    if (!st.trim() || !tr.trim() || busy) return;
    setBusy(true);
    try {
      await window.API.upsertGlossary(novelId, { source_term: st.trim(), translation: tr.trim(), term_type: type, locked: true });
      setSt(""); setTr(""); reload();
    } finally { setBusy(false); }
  }
  const toggleLock = async (g) => {
    await window.API.upsertGlossary(novelId, { source_term: g.source_term, translation: g.translation, term_type: g.term_type, notes: g.notes, locked: !g.locked });
    reload();
  };
  const del = async (g) => { await window.API.delGlossary(novelId, g.id); reload(); };

  return React.createElement(React.Fragment, null,
    React.createElement("button", {
      className: "section-eyebrow collapse-head", style: { marginTop: 28 },
      onClick: () => setOpen(o => !o), "aria-expanded": open,
    },
      `Translation glossary (${glossary.length})`,
      React.createElement(Icon, { name: "chevronDown", size: 15, className: "collapse-caret" + (open ? " open" : "") })
    ),
    open && React.createElement("div", { className: "card", style: { padding: 14 } },
      React.createElement("form", { className: "row", style: { gap: 8, flexWrap: "wrap", marginBottom: glossary.length ? 12 : 0 }, onSubmit: add },
        React.createElement("input", { className: "gl-input", value: st, onChange: e => setSt(e.target.value), placeholder: "Source term (林轩)" }),
        React.createElement("input", { className: "gl-input", value: tr, onChange: e => setTr(e.target.value), placeholder: "English (Lin Xuan)" }),
        React.createElement("select", { className: "gl-input", style: { flex: "0 0 104px" }, value: type, onChange: e => setType(e.target.value) },
          ["name", "place", "skill", "item", "term"].map(o => React.createElement("option", { key: o, value: o }, o))),
        React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy }, "Add")
      ),
      glossary.map(g => React.createElement("div", { key: g.id, className: "gl-row" },
        React.createElement("span", { className: "gl-src" }, g.source_term),
        React.createElement(Icon, { name: "arrowRight", size: 13, className: "muted" }),
        React.createElement("span", { className: "gl-tr" }, g.translation),
        g.term_type && React.createElement("span", { className: "chip" }, g.term_type),
        React.createElement("div", { className: "grow" }),
        React.createElement("button", { className: "icon-btn" + (g.locked ? " active" : ""), title: g.locked ? "Locked — won't auto-change" : "Click to lock", onClick: () => toggleLock(g) },
          React.createElement(Icon, { name: g.locked ? "lock" : "unlock", size: 15 })),
        React.createElement("button", { className: "icon-btn", title: "Delete", onClick: () => del(g) }, React.createElement(Icon, { name: "x", size: 15 }))
      ))
    )
  );
}

function ShelfTagsControls({ novel, reloadNovel }) {
  const shelf = novel.shelf || "";
  const tags = novel.status_tags || [];
  const tt = novel.translation_type ? window.TRANSLATION_TYPE_LABELS[novel.translation_type] : null;
  const [busy, setBusy] = useState(false);

  const patch = async (body) => {
    if (busy) return;
    setBusy(true);
    try { await window.API.updateNovel(novel.id, body); reloadNovel(); }
    finally { setBusy(false); }
  };
  const setShelf = (s) => patch({ shelf: shelf === s ? "" : s });   // tap the active shelf to clear it
  const toggleTag = (t) => patch({ status_tags: tags.includes(t) ? tags.filter(x => x !== t) : [...tags, t] });

  return React.createElement("div", { className: "shelf-tags" },
    React.createElement("div", { className: "st-group" },
      React.createElement("span", { className: "st-label" }, "Shelf"),
      React.createElement("div", { className: "rs-seg" },
        window.SHELF_ORDER.map(s => React.createElement("button", {
          key: s, className: shelf === s ? "active" : "", onClick: () => setShelf(s),
        }, window.SHELF_LABELS[s])))
    ),
    React.createElement("div", { className: "st-group" },
      React.createElement("span", { className: "st-label" }, "Tags"),
      React.createElement("div", { className: "st-tags" },
        window.STATUS_TAG_ORDER.map(t => React.createElement("button", {
          key: t, className: "tag-toggle" + (tags.includes(t) ? " on" : ""), onClick: () => toggleTag(t),
        }, window.STATUS_TAG_LABELS[t])),
        tt && React.createElement("span", { className: "chip tt-chip", title: "Auto-detected from sources" }, tt))
    )
  );
}

function NovelDetail({ novelId, novel, reloadNovel, openReader, nav, openLibrary }) {
  const [toc, setToc] = useState(null);    // null = loading
  const [adapters, setAdapters] = useState([]);
  const [addingSource, setAddingSource] = useState(false);
  const [editSourceId, setEditSourceId] = useState(null);
  const [editing, setEditing] = useState(false);
  const [bookmarks, setBookmarks] = useState([]);
  const [glossary, setGlossary] = useState([]);
  const [maxCh, setMaxCh] = useState("");
  const [msg, setMsg] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadToc = useCallback(() => {
    if (novelId == null) return;
    window.API.chapters(novelId).then(setToc).catch(() => setToc([]));
  }, [novelId]);
  const loadBookmarks = useCallback(() => {
    if (novelId == null) return;
    window.API.bookmarks(novelId).then(setBookmarks).catch(() => setBookmarks([]));
  }, [novelId]);
  const loadGlossary = useCallback(() => {
    if (novelId == null) return;
    window.API.glossary(novelId).then(setGlossary).catch(() => setGlossary([]));
  }, [novelId]);

  useEffect(() => { loadToc(); loadBookmarks(); loadGlossary(); }, [loadToc, loadBookmarks, loadGlossary]);
  useEffect(() => { window.API.adapters().then(setAdapters).catch(() => setAdapters([])); }, []);

  if (!novel) return React.createElement("div", { className: "page" }, React.createElement(Loading, { label: "Loading novel…" }));

  const progress = novel.progress || {};
  const startAt = progress.last_chapter != null ? progress.last_chapter : (novel.min_chapter || 1);
  const hasChapters = (novel.chapter_count || 0) > 0;
  const hasRaw = (novel.sources || []).some(s => s.is_raw);

  async function doScrape() {
    setMsg("Scraping started in the background…");
    try {
      await window.API.scrape(novelId, { max_chapters: maxCh.trim() ? parseInt(maxCh) : null });
    } catch (e) {
      setMsg("Scrape failed: " + (e.message || "error"));
    }
  }

  async function buildCodex() {
    setMsg("Codex build started in the background (chunk → embed → extract)…");
    try { await window.API.codexBuild(novelId, {}); reloadNovel(); }
    catch (e) { setMsg("Codex build failed: " + (e.message || "error")); }
  }

  async function doTranslate() {
    setMsg("Translation started in the background (glossary-consistent)…");
    try { await window.API.translate(novelId, {}); }
    catch (e) { setMsg("Translate failed: " + (e.message || "error")); }
  }

  async function doSeedGlossary() {
    try { const r = await window.API.seedGlossary(novelId); setMsg(`Seeded ${r.seeded} glossary terms from the codex.`); loadGlossary(); }
    catch (e) { setMsg("Seed failed: " + (e.message || "error")); }
  }

  async function doDelete() {
    if (deleting) return;
    setDeleting(true);
    try {
      await window.API.deleteNovel(novelId);
      setConfirmDelete(false);
      openLibrary();   // novel is gone — leave the detail view
    } catch (e) {
      setMsg("Delete failed: " + (e.message || "error"));
      setDeleting(false);
    }
  }

  return React.createElement("div", { className: "page" },
    // header
    editing
      ? React.createElement(NovelEditForm, { novel, onSaved: () => { setEditing(false); reloadNovel(); }, onCancel: () => setEditing(false), onRequestDelete: () => setConfirmDelete(true) })
      : React.createElement("div", { className: "novel-hero" },
        React.createElement("div", { className: "novel-hero-cover" },
          novel.cover_url ? React.createElement("img", { src: novel.cover_url, alt: "" })
            : React.createElement("div", { className: "novel-cover-ph lg" }, React.createElement(Icon, { name: "book", size: 40 }))
        ),
        React.createElement("div", { className: "novel-hero-body" },
          React.createElement("div", { className: "row", style: { gap: 10, alignItems: "flex-start" } },
            React.createElement("h1", { className: "serif", style: { margin: "0 0 6px", flex: 1 } }, novel.title),
            React.createElement("button", { className: "icon-btn", onClick: () => setEditing(true), title: "Edit novel" },
              React.createElement(Icon, { name: "edit", size: 17 }))
          ),
          novel.author && React.createElement("div", { className: "muted" }, novel.author),
          novel.description && React.createElement("p", { style: { color: "var(--ink-2)", lineHeight: 1.6, maxWidth: "60ch" } }, novel.description),
          React.createElement("div", { className: "row", style: { gap: 10, marginTop: 14, flexWrap: "wrap" } },
            hasChapters && React.createElement("button", { className: "btn btn-primary", onClick: () => openReader(startAt) },
              React.createElement(Icon, { name: "book", size: 16 }),
              progress.last_chapter != null ? `Continue · Ch. ${startAt}` : "Start reading"),
            React.createElement("span", { className: "chip mono" }, `${novel.chapter_count} chapters`),
            novel.max_chapter != null && React.createElement("span", { className: "chip mono" }, `ch. ${novel.min_chapter}–${novel.max_chapter}`),
            novel.codex_enabled && React.createElement("button", { className: "btn btn-ghost", onClick: () => nav("browse") },
              React.createElement(Icon, { name: "compass", size: 16 }), "Open codex")
          ),
          React.createElement(ShelfTagsControls, { novel, reloadNovel })
        )
      ),

    msg && React.createElement("div", { className: "card", style: { padding: "10px 16px", marginBottom: 16, fontSize: 13.5 } }, msg),

    // sources + scrape
    React.createElement("div", { className: "novel-cols" },
      React.createElement("div", null,
        React.createElement("p", { className: "section-eyebrow" }, "Sources"),
        React.createElement("div", { className: "card", style: { padding: 12 } },
          (novel.sources || []).map(s => React.createElement("div", { key: s.id },
            React.createElement("div", { className: "source-row" },
              React.createElement("div", { className: "grow" },
                React.createElement("div", { style: { fontWeight: 600 } }, s.label || s.adapter, s.is_raw && React.createElement("span", { className: "chip", style: { marginLeft: 8 } }, "raw · " + s.language)),
                React.createElement("div", { className: "muted", style: { fontSize: 12.5, wordBreak: "break-all" } }, s.start_url)
              ),
              s.chapter_offset ? React.createElement("span", { className: "chip mono" }, `${s.chapter_offset > 0 ? "+" : ""}${s.chapter_offset}`) : null,
              React.createElement("button", { className: "icon-btn", title: "Edit offset", onClick: () => setEditSourceId(editSourceId === s.id ? null : s.id) },
                React.createElement(Icon, { name: "edit", size: 15 }))
            ),
            editSourceId === s.id && React.createElement(EditSourceForm, {
              novelId, source: s,
              onCancel: () => setEditSourceId(null),
              onSaved: (r) => {
                setEditSourceId(null);
                setMsg(r && r.renumbered ? `Renumbered ${r.renumbered} chapters to the new offset.` : "Source updated.");
                reloadNovel(); loadToc();
              },
            })
          )),
          (novel.sources || []).length === 0 && React.createElement("div", { className: "muted", style: { padding: 8 } }, "No sources yet."),
          !addingSource && React.createElement("button", { className: "btn btn-ghost", style: { marginTop: 8 }, onClick: () => setAddingSource(true) },
            React.createElement(Icon, { name: "sparkles", size: 15 }), "Add source")
        ),
        addingSource && React.createElement(AddSourceForm, {
          novelId, adapters, onCancel: () => setAddingSource(false),
          onAdded: () => { setAddingSource(false); reloadNovel(); },
        })
      ),
      React.createElement("div", null,
        React.createElement("p", { className: "section-eyebrow" }, "Pipeline"),
        React.createElement("div", { className: "card", style: { padding: 16 } },
          React.createElement("div", { className: "row", style: { gap: 10, alignItems: "flex-end", flexWrap: "wrap" } },
            React.createElement("label", { className: "field", style: { flex: "0 0 130px" } },
              React.createElement("span", null, "Max chapters"),
              React.createElement("input", { value: maxCh, onChange: e => setMaxCh(e.target.value), placeholder: "(all)", inputMode: "numeric" })
            ),
            React.createElement("button", { className: "btn btn-primary", onClick: doScrape },
              React.createElement(Icon, { name: "refresh", size: 15 }), "Scrape"),
            React.createElement("button", { className: "btn btn-ghost", onClick: loadToc },
              React.createElement(Icon, { name: "refresh", size: 15 }), "Refresh TOC")
          ),
          hasRaw && React.createElement("div", { style: { marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 } },
            React.createElement("div", { className: "row", style: { gap: 10, flexWrap: "wrap" } },
              React.createElement("button", { className: "btn btn-ghost", onClick: doTranslate },
                React.createElement(Icon, { name: "refresh", size: 15 }), "Translate raw chapters"),
              novel.codex_enabled && React.createElement("button", { className: "btn btn-ghost", onClick: doSeedGlossary },
                React.createElement(Icon, { name: "merge", size: 15 }), "Seed glossary from codex")),
            React.createElement("p", { className: "muted", style: { fontSize: 12.5, marginTop: 8, marginBottom: 0 } },
              "Reading already translates on demand; this pre-translates the whole raw source.")
          ),
          React.createElement("div", { style: { marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 } },
            React.createElement("button", { className: "btn btn-ghost", onClick: buildCodex },
              React.createElement(Icon, { name: "brain", size: 15 }), novel.codex_enabled ? "Rebuild codex" : "Build codex"),
            React.createElement("p", { className: "muted", style: { fontSize: 12.5, marginTop: 8, marginBottom: 0 } },
              "Builds the spoiler-safe knowledge base from scraped chapters. Runs in the background.")
          )
        )
      )
    ),

    // translation glossary (raw novels)
    (hasRaw || glossary.length > 0) && React.createElement(GlossaryEditor, { novelId, glossary, reload: loadGlossary }),

    // bookmarks
    bookmarks.length > 0 && React.createElement(React.Fragment, null,
      React.createElement("p", { className: "section-eyebrow", style: { marginTop: 28 } }, "Bookmarks"),
      React.createElement("div", { className: "card toc" },
        bookmarks.map(b => React.createElement("div", { key: b.id, className: "toc-row", style: { cursor: "default" } },
          React.createElement("button", { className: "bm-jump", onClick: () => openReader(b.chapter) },
            React.createElement(Icon, { name: "book", size: 14, className: "muted" }),
            React.createElement("span", { className: "toc-num mono" }, `Ch. ${b.chapter}`),
            React.createElement("span", { className: "toc-title" }, b.note || "Bookmarked")
          ),
          React.createElement("button", {
            className: "icon-btn", title: "Remove bookmark",
            onClick: async () => { await window.API.delBookmark(novelId, b.id); loadBookmarks(); },
          }, React.createElement(Icon, { name: "x", size: 15 }))
        ))
      )
    ),

    // TOC
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 28 } }, "Contents"),
    toc == null
      ? React.createElement(Loading, { label: "Loading chapters…" })
      : toc.length === 0
        ? React.createElement(EmptyState, { icon: "book", title: "No chapters yet", body: "Use Scrape above to fetch chapters from the source." })
        : React.createElement("div", { className: "card toc" }, buildToc(toc, progress, openReader)),

    confirmDelete && React.createElement(ConfirmDialog, {
      title: `Delete “${novel.title}”?`,
      requireText: novel.title,
      confirmLabel: "Delete permanently",
      busy: deleting,
      onCancel: () => setConfirmDelete(false),
      onConfirm: doDelete,
      body: React.createElement("div", null,
        React.createElement("p", { className: "muted", style: { fontSize: 13.8, lineHeight: 1.55, margin: "0 0 8px" } },
          "This permanently removes the novel and everything tied to it — there's no undo."),
        React.createElement("ul", { className: "muted", style: { fontSize: 13.2, lineHeight: 1.6, margin: 0, paddingLeft: 18 } },
          React.createElement("li", null, `${novel.chapter_count || 0} chapters (text + translations)`),
          React.createElement("li", null, "the codex, bookmarks, glossary and reading progress"),
          React.createElement("li", null, "imported files, covers and illustrations on disk"))
      ),
    })
  );
}

window.NovelDetail = NovelDetail;
