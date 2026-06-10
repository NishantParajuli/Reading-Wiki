/* ============================================================
   Novel detail — the per-novel hub: continue reading, sources, scraping,
   codex build, and the table of contents.
   ============================================================ */
function AddSourceForm({ novelId, adapters, onAdded, onCancel }) {
  const [adapter, setAdapter] = useState(adapters[0] ? adapters[0].name : "fenrirealm");
  const [startUrl, setStartUrl] = useState("");
  const [language, setLanguage] = useState("en");
  const [isRaw, setIsRaw] = useState(false);
  const [continuesFrom, setContinuesFrom] = useState("");
  const [localStart, setLocalStart] = useState("");
  const [titleSelector, setTitleSelector] = useState("");
  const [contentSelector, setContentSelector] = useState("");
  const [nextSelector, setNextSelector] = useState("");
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
    
    const config = {};
    if (adapter === "generic") {
      if (titleSelector.trim()) config.title_selector = titleSelector.trim();
      if (contentSelector.trim()) config.content_selector = contentSelector.trim();
      if (nextSelector.trim()) config.next_selector = nextSelector.trim();
    } else if (adapter === "generic_xpath") {
      if (titleSelector.trim()) config.title_xpath = titleSelector.trim();
      if (contentSelector.trim()) config.content_xpath = contentSelector.trim();
      if (nextSelector.trim()) config.next_xpath = nextSelector.trim();
    }

    try {
      await window.API.addSource(novelId, {
        adapter,
        start_url: startUrl.trim(),
        language,
        is_raw: isRaw,
        chapter_offset: offset,
        config: Object.keys(config).length > 0 ? config : null,
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
    (adapter === "generic" || adapter === "generic_xpath") && React.createElement("div", { className: "card", style: { padding: 12, marginTop: 8, marginBottom: 8, display: "flex", flexDirection: "column", gap: 8, backgroundColor: "var(--bg-2)" } },
      React.createElement("p", { className: "section-eyebrow", style: { margin: 0, fontSize: 12 } }, "Advanced Selectors (Optional)"),
      React.createElement("div", { className: "row", style: { gap: 12, flexWrap: "wrap" } },
        React.createElement("label", { className: "field", style: { flex: "1 1 120px" } },
          React.createElement("span", null, adapter === "generic_xpath" ? "Title XPath" : "Title Selector"),
          React.createElement("input", { value: titleSelector, onChange: e => setTitleSelector(e.target.value), placeholder: adapter === "generic_xpath" ? "//h1" : "h1" })
        ),
        React.createElement("label", { className: "field", style: { flex: "1 1 120px" } },
          React.createElement("span", null, adapter === "generic_xpath" ? "Content XPath" : "Content Selector"),
          React.createElement("input", { value: contentSelector, onChange: e => setContentSelector(e.target.value), placeholder: adapter === "generic_xpath" ? "//article" : "article" })
        ),
        React.createElement("label", { className: "field", style: { flex: "1 1 120px" } },
          React.createElement("span", null, adapter === "generic_xpath" ? "Next XPath" : "Next Selector"),
          React.createElement("input", { value: nextSelector, onChange: e => setNextSelector(e.target.value), placeholder: adapter === "generic_xpath" ? "//a[@rel='next']" : "a[rel=next]" })
        )
      )
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

function NovelEditForm({ novel, onSaved, onCancel }) {
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
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy }, busy ? "Saving…" : "Save"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel"))
  );
}

function GlossaryEditor({ novelId, glossary, reload }) {
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
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 28 } }, `Translation glossary (${glossary.length})`),
    React.createElement("div", { className: "card", style: { padding: 14 } },
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

function NovelDetail({ novelId, novel, reloadNovel, openReader, nav }) {
  const [toc, setToc] = useState(null);    // null = loading
  const [adapters, setAdapters] = useState([]);
  const [addingSource, setAddingSource] = useState(false);
  const [editing, setEditing] = useState(false);
  const [bookmarks, setBookmarks] = useState([]);
  const [glossary, setGlossary] = useState([]);
  const [maxCh, setMaxCh] = useState("");
  const [msg, setMsg] = useState(null);

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

  return React.createElement("div", { className: "page" },
    // header
    editing
      ? React.createElement(NovelEditForm, { novel, onSaved: () => { setEditing(false); reloadNovel(); }, onCancel: () => setEditing(false) })
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
        )
      )
    ),

    msg && React.createElement("div", { className: "card", style: { padding: "10px 16px", marginBottom: 16, fontSize: 13.5 } }, msg),

    // sources + scrape
    React.createElement("div", { className: "novel-cols" },
      React.createElement("div", null,
        React.createElement("p", { className: "section-eyebrow" }, "Sources"),
        React.createElement("div", { className: "card", style: { padding: 12 } },
          (novel.sources || []).map(s => React.createElement("div", { key: s.id, className: "source-row" },
            React.createElement("div", { className: "grow" },
              React.createElement("div", { style: { fontWeight: 600 } }, s.label || s.adapter, s.is_raw && React.createElement("span", { className: "chip", style: { marginLeft: 8 } }, "raw · " + s.language)),
              React.createElement("div", { className: "muted", style: { fontSize: 12.5, wordBreak: "break-all" } }, s.start_url)
            ),
            s.chapter_offset ? React.createElement("span", { className: "chip mono" }, `+${s.chapter_offset}`) : null
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
        : React.createElement("div", { className: "card toc" },
            toc.map(ch => React.createElement("button", {
              key: ch.number, className: "toc-row" + (progress.last_chapter === ch.number ? " current" : ""),
              onClick: () => openReader(ch.number),
            },
              React.createElement("span", { className: "toc-num mono" }, ch.number),
              React.createElement("span", { className: "toc-title" }, ch.title || `Chapter ${ch.number}`),
              !ch.has_content && ch.translation_status === "pending"
                ? React.createElement("span", { className: "chip", title: "Raw — translates on open" }, "raw")
                : null,
              React.createElement(Icon, { name: "arrowRight", size: 15, className: "muted" })
            ))
          )
  );
}

window.NovelDetail = NovelDetail;
