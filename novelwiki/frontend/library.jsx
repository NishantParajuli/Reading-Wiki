/* ============================================================
   Library — the landing surface: a grid of novels + Add Novel.
   ============================================================ */
function NovelCard({ n, openNovel }) {
  const max = n.max_chapter || 0;
  const read = n.max_chapter_read || 0;
  const pct = max > 0 ? Math.round(Math.min(100, (read / max) * 100)) : 0;
  const cont = n.last_chapter != null ? `Continue · Ch. ${n.last_chapter}` : (n.chapter_count ? "Start reading" : "Not scraped yet");
  return React.createElement("button", { className: "novel-card", onClick: () => openNovel(n.id) },
    React.createElement("div", { className: "novel-cover" },
      n.cover_url
        ? React.createElement("img", { src: n.cover_url, alt: "" })
        : React.createElement("div", { className: "novel-cover-ph" }, React.createElement(Icon, { name: "book", size: 30 }))
    ),
    React.createElement("div", { className: "novel-card-body" },
      React.createElement("div", { className: "novel-card-title" }, n.title),
      n.author && React.createElement("div", { className: "muted", style: { fontSize: 13 } }, n.author),
      React.createElement("div", { className: "progress-track", style: { marginTop: 12 } },
        React.createElement("div", { className: "progress-fill", style: { width: pct + "%" } })
      ),
      React.createElement("div", { className: "novel-card-foot" },
        React.createElement("span", { className: "chip mono" }, `${n.chapter_count} ch.`),
        React.createElement("span", { className: "muted", style: { fontSize: 12.5, marginLeft: "auto" } }, cont)
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

function Library({ openNovel }) {
  const [novels, setNovels] = useState(null);  // null = loading
  const [adapters, setAdapters] = useState([]);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    window.API.novels().then(setNovels).catch(() => setNovels([]));
  }, []);

  useEffect(() => {
    load();
    window.API.adapters().then(setAdapters).catch(() => setAdapters([]));
  }, [load]);

  return React.createElement("div", { className: "page" },
    React.createElement("div", { className: "lib-head" },
      React.createElement("div", null,
        React.createElement("h1", { className: "lib-title" }, "Your Library"),
        React.createElement("p", { className: "muted", style: { margin: "4px 0 0" } }, "Everything you're reading, in one place.")
      ),
      !adding && React.createElement("button", { className: "btn btn-primary", onClick: () => setAdding(true) },
        React.createElement(Icon, { name: "sparkles", size: 16 }), "Add novel")
    ),

    adding && React.createElement(AddNovelForm, {
      adapters,
      onCancel: () => setAdding(false),
      onCreated: (id) => { setAdding(false); load(); openNovel(id); },
    }),

    novels == null
      ? React.createElement(Loading, { label: "Loading your library…" })
      : novels.length === 0 && !adding
        ? React.createElement(EmptyState, { icon: "book", title: "No novels yet", body: "Add your first novel to start reading." })
        : React.createElement("div", { className: "lib-grid" },
            novels.map(n => React.createElement(NovelCard, { key: n.id, n, openNovel }))
          )
  );
}

Object.assign(window, { Library, NovelCard });
