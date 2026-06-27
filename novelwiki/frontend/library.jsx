/* ============================================================
   Library — the landing surface: a grid of novels + Add Novel.
   Plus Discover (the shared Global/Public library) for multi-user.
   ============================================================ */
const VIS_LABELS = { global: "Global", public: "Public", private: "Private" };

function NovelCard({ n, openNovel, onChanged }) {
  const max = n.max_chapter || 0;
  const read = n.max_chapter_read || 0;
  const pct = max > 0 ? Math.round(Math.min(100, (read / max) * 100)) : 0;
  const cont = n.last_chapter != null ? `Continue · Ch. ${n.last_chapter}` : (n.chapter_count ? "Start reading" : "Not scraped yet");
  const tt = n.translation_type ? window.TRANSLATION_TYPE_LABELS[n.translation_type] : null;
  const tags = n.status_tags || [];

  async function setShelf(e) {
    e.stopPropagation();
    try { await window.API.updateNovel(n.id, { shelf: e.target.value }); onChanged && onChanged(); }
    catch (err) { /* keep the card as-is on failure */ }
  }

  return React.createElement("div", {
    className: "novel-card", role: "button", tabIndex: 0,
    onClick: () => openNovel(n.id),
    onKeyDown: e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNovel(n.id); } },
  },
    React.createElement("div", { className: "novel-cover" },
      n.cover_url
        ? React.createElement("img", { src: n.cover_url, alt: "", loading: "lazy" })
        : React.createElement("div", { className: "novel-cover-ph" }, React.createElement(Icon, { name: "book", size: 30 }))
    ),
    React.createElement("div", { className: "novel-card-body" },
      React.createElement("div", { className: "novel-card-title" }, n.title),
      n.author && React.createElement("div", { className: "muted", style: { fontSize: 13 } }, n.author),
      (tt || tags.length > 0 || (n.visibility && n.visibility !== "private")) && React.createElement("div", { className: "card-tags" },
        n.visibility && n.visibility !== "private" && React.createElement("span", { className: "chip vis-chip", title: "Shared library" }, VIS_LABELS[n.visibility]),
        tt && React.createElement("span", { className: "chip tt-chip", title: "Auto-detected from sources" }, tt),
        tags.map(t => React.createElement("span", { key: t, className: "chip tag-chip" }, window.STATUS_TAG_LABELS[t] || t))
      ),
      React.createElement("div", { className: "progress-track", style: { marginTop: 12 } },
        React.createElement("div", { className: "progress-fill", style: { width: pct + "%" } })
      ),
      React.createElement("div", { className: "novel-card-foot" },
        React.createElement("span", { className: "chip mono" }, `${n.chapter_count} ch.`),
        React.createElement("span", { className: "muted", style: { fontSize: 12.5, marginLeft: "auto" } }, cont)
      ),
      React.createElement("select", {
        className: "shelf-select", value: n.shelf || "", title: "Add to a shelf",
        onClick: e => e.stopPropagation(), onChange: setShelf,
      },
        React.createElement("option", { value: "" }, "+ Shelf"),
        window.SHELF_ORDER.map(s => React.createElement("option", { key: s, value: s }, window.SHELF_LABELS[s]))
      )
    )
  );
}

function AddNovelForm({ adapters, onCreated, onCancel }) {
  const [title, setTitle] = useState("");
  const [adapter, setAdapter] = useState(adapters[0] ? adapters[0].name : "fenrirealm");
  const [startUrl, setStartUrl] = useState("");
  const [language, setLanguage] = useState("en");
  const [isRaw, setIsRaw] = useState(false);
  const [codex, setCodex] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  // Default the language to the chosen adapter's default.
  useEffect(() => {
    const a = adapters.find(x => x.name === adapter);
    if (a && a.default_language) setLanguage(a.default_language);
  }, [adapter]); // eslint-disable-line

  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || !startUrl.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      const res = await window.API.createNovel({
        title: title.trim(),
        codex_enabled: codex,
        original_language: language,
        source: { adapter, start_url: startUrl.trim(), language, is_raw: isRaw },
      });
      onCreated(res.id);
    } catch (e2) {
      setErr(e2.message || "Could not create the novel.");
      setBusy(false);
    }
  }

  return React.createElement("form", { className: "card add-novel", onSubmit: submit },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Add a novel"),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Title"),
      React.createElement("input", { value: title, onChange: e => setTitle(e.target.value), placeholder: "e.g. I Was Trapped in a Bad Ending…", autoFocus: true })
    ),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Scraping technique"),
      React.createElement("select", { value: adapter, onChange: e => setAdapter(e.target.value) },
        adapters.map(a => React.createElement("option", { key: a.name, value: a.name }, a.label))
      )
    ),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "First chapter URL"),
      React.createElement("input", { value: startUrl, onChange: e => setStartUrl(e.target.value), placeholder: "https://…/series/<slug>/1" })
    ),
    React.createElement("div", { className: "row", style: { gap: 16, flexWrap: "wrap" } },
      React.createElement("label", { className: "field", style: { flex: "0 0 120px" } },
        React.createElement("span", null, "Language"),
        React.createElement("input", { value: language, onChange: e => setLanguage(e.target.value), placeholder: "en" })
      ),
      React.createElement("label", { className: "check" },
        React.createElement("input", { type: "checkbox", checked: isRaw, onChange: e => setIsRaw(e.target.checked) }),
        "Raw (needs translation)"
      ),
      React.createElement("label", { className: "check" },
        React.createElement("input", { type: "checkbox", checked: codex, onChange: e => setCodex(e.target.checked) }),
        "Enable codex"
      )
    ),
    err && React.createElement("div", { className: "muted", style: { color: "var(--rose, crimson)", fontSize: 13 } }, err),
    React.createElement("div", { className: "row", style: { gap: 10, marginTop: 4 } },
      React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy },
        React.createElement(Icon, { name: "check", size: 16 }), busy ? "Creating…" : "Add to library"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel")
    )
  );
}

const LIBRARY_TABS = [
  { id: "all", label: "All" },
  { id: "reading", label: "Reading" },
  { id: "to_read", label: "To read" },
  { id: "completed", label: "Completed" },
];

function Library({ openNovel, openImport, openDiscover }) {
  const [novels, setNovels] = useState(null);  // null = loading
  const [adapters, setAdapters] = useState([]);
  const [adding, setAdding] = useState(false);
  const [tab, setTab] = useState(() => localStorage.getItem("nw-lib-tab") || "all");

  const load = useCallback(() => {
    window.API.novels().then(setNovels).catch(() => setNovels([]));
  }, []);

  useEffect(() => {
    load();
    window.API.adapters().then(setAdapters).catch(() => setAdapters([]));
  }, [load]);
  useEffect(() => { localStorage.setItem("nw-lib-tab", tab); }, [tab]);

  const all = novels || [];
  const counts = { all: all.length, reading: 0, to_read: 0, completed: 0 };
  all.forEach(n => { if (n.shelf && counts[n.shelf] != null) counts[n.shelf]++; });
  const shown = tab === "all" ? all : all.filter(n => n.shelf === tab);

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "lib-head" },
      React.createElement("div", null,
        React.createElement("h1", { className: "lib-title" }, "Your Library"),
        React.createElement("p", { className: "muted", style: { margin: "4px 0 0" } }, "Everything you're reading, in one place.")
      ),
      !adding && React.createElement("div", { className: "row", style: { gap: 8 } },
        openDiscover && React.createElement("button", { className: "btn btn-ghost", onClick: openDiscover },
          React.createElement(Icon, { name: "compass", size: 16 }), "Discover"),
        openImport && React.createElement("button", { className: "btn btn-ghost", onClick: openImport },
          React.createElement(Icon, { name: "book", size: 16 }), "Import EPUB"),
        React.createElement("button", { className: "btn btn-primary", onClick: () => setAdding(true) },
          React.createElement(Icon, { name: "sparkles", size: 16 }), "Add novel"))
    ),

    novels != null && React.createElement("div", { className: "lib-tabs" },
      LIBRARY_TABS.map(tb => React.createElement("button", {
        key: tb.id, className: "lib-tab" + (tab === tb.id ? " active" : ""), onClick: () => setTab(tb.id),
      }, tb.label, React.createElement("span", { className: "lib-tab-count" }, counts[tb.id])))
    ),

    adding && React.createElement(AddNovelForm, {
      adapters,
      onCancel: () => setAdding(false),
      onCreated: (id) => { setAdding(false); load(); openNovel(id); },
    }),

    novels == null
      ? React.createElement(Loading, { label: "Loading your library…" })
      : all.length === 0 && !adding
        ? React.createElement(EmptyState, { icon: "book", title: "No novels yet", body: "Add your first novel to start reading." })
        : shown.length === 0
          ? React.createElement(EmptyState, { icon: "book", title: `Nothing on “${(LIBRARY_TABS.find(t => t.id === tab) || {}).label}” yet`, body: "Use the shelf picker on a novel to add it here." })
          : React.createElement("div", { className: "lib-grid" },
              shown.map(n => React.createElement(NovelCard, { key: n.id, n, openNovel, onChanged: load }))
            )
  );
}

/* ── Discover: the shared Global + Public library you can add to your own ── */
function DiscoverCard({ n, openNovel, onAdded }) {
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(false);
  async function add(e) {
    e.stopPropagation();
    setAdding(true);
    try { await window.API.addToLibrary(n.id); setAdded(true); onAdded && onAdded(n.id); }
    catch (err) { setAdding(false); }
  }
  return React.createElement("div", {
    className: "novel-card", role: "button", tabIndex: 0,
    onClick: () => openNovel(n.id),
    onKeyDown: e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNovel(n.id); } },
  },
    React.createElement("div", { className: "novel-cover" },
      n.cover_url
        ? React.createElement("img", { src: n.cover_url, alt: "", loading: "lazy" })
        : React.createElement("div", { className: "novel-cover-ph" }, React.createElement(Icon, { name: "book", size: 30 }))
    ),
    React.createElement("div", { className: "novel-card-body" },
      React.createElement("div", { className: "novel-card-title" }, n.title),
      n.author && React.createElement("div", { className: "muted", style: { fontSize: 13 } }, n.author),
      React.createElement("div", { className: "card-tags" },
        React.createElement("span", { className: "chip vis-chip" }, VIS_LABELS[n.visibility]),
        n.owner_username && n.visibility === "public" &&
          React.createElement("span", { className: "chip", title: "Uploaded by" }, "@" + n.owner_username)
      ),
      React.createElement("div", { className: "novel-card-foot" },
        React.createElement("span", { className: "chip mono" }, `${n.chapter_count} ch.`),
        React.createElement("button", {
          className: "btn btn-primary", style: { marginLeft: "auto", padding: "5px 10px" },
          disabled: adding || added, onClick: add,
        }, added ? "Added ✓" : adding ? "…" : "Add to library")
      )
    )
  );
}

function Discover({ openNovel, openLibrary }) {
  const [items, setItems] = useState(null);
  const [q, setQ] = useState("");
  const load = useCallback((query) => {
    setItems(null);
    window.API.discover(query || "").then(setItems).catch(() => setItems([]));
  }, []);
  useEffect(() => { load(""); }, [load]);

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "lib-head" },
      React.createElement("div", null,
        React.createElement("h1", { className: "lib-title" }, "Discover"),
        React.createElement("p", { className: "muted", style: { margin: "4px 0 0" } }, "The shared library — add anything to start reading with your own progress.")
      ),
      React.createElement("div", { className: "row", style: { gap: 8 } },
        openLibrary && React.createElement("button", { className: "btn btn-ghost", onClick: openLibrary },
          React.createElement(Icon, { name: "arrowLeft", size: 16 }), "My library")
      )
    ),
    React.createElement("form", { className: "row", style: { gap: 8, marginBottom: 14 }, onSubmit: e => { e.preventDefault(); load(q); } },
      React.createElement("input", {
        className: "auth-input", style: { maxWidth: 340 }, value: q, placeholder: "Search shared titles…",
        onChange: e => setQ(e.target.value),
      }),
      React.createElement("button", { className: "btn btn-ghost", type: "submit" }, "Search")
    ),
    items == null
      ? React.createElement(Loading, { label: "Loading the shared library…" })
      : items.length === 0
        ? React.createElement(EmptyState, { icon: "compass", title: "Nothing to discover yet", body: "Global novels and other readers' public uploads show up here." })
        : React.createElement("div", { className: "lib-grid" },
            items.map(n => React.createElement(DiscoverCard, {
              key: n.id, n, openNovel,
              onAdded: (id) => setItems(prev => prev.filter(x => x.id !== id)),
            }))
          )
  );
}

Object.assign(window, { Library, NovelCard, Discover });
