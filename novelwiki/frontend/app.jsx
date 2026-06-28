/* ============================================================
   App shell — library → novel → reader, plus the per-novel codex.

   The library is the landing surface. Opening a novel enters a per-novel context
   with three tabs: Contents (TOC + continue reading), Codex, and Ask. The reader
   is a full-bleed view opened from Contents. The chapter-ceiling control only
   appears in the codex/ask context and defaults to the reader's progress.
   ============================================================ */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accentHue": 64,
  "headings": "Literary",
  "corners": "Rounded"
}/*EDITMODE-END*/;

const ACCENTS = [
  { hue: 64, name: "Honey" },
  { hue: 42, name: "Amber" },
  { hue: 28, name: "Clay" },
  { hue: 12, name: "Rose" },
  { hue: 152, name: "Sage" },
  { hue: 250, name: "Dusk" },
];
const CORNERS = { Soft: [26, 16, 34], Rounded: [18, 12, 26], Sharp: [8, 6, 12] };

function AccentSwatches({ value, onChange }) {
  return React.createElement("div", { style: { display: "flex", flexWrap: "wrap", gap: 8 } },
    ACCENTS.map(a => React.createElement("button", {
      key: a.hue, title: a.name, onClick: () => onChange(a.hue),
      style: {
        width: 34, height: 34, borderRadius: 10, cursor: "pointer",
        background: `oklch(0.74 0.13 ${a.hue})`,
        border: value === a.hue ? "2.5px solid var(--ink)" : "2.5px solid transparent",
        boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
      },
    }))
  );
}

function CeilingBar({ ceiling, setCeiling, meta, stats }) {
  const min = (meta && meta.min) || 1;
  const max = (meta && meta.max) || min;
  const title = stats && stats.ceiling_title;
  const revealed = stats == null ? "—" : stats.entities_revealed;
  return React.createElement("div", { className: "ceiling" },
    React.createElement("div", { className: "ceiling-label" },
      React.createElement(Icon, { name: "book", size: 16, className: "lk" }),
      React.createElement("div", { className: "col", style: { gap: 1 } },
        React.createElement("span", { className: "ceiling-eyebrow" }, "Codex bounded to"),
        React.createElement("b", null, title ? `Ch. ${ceiling} · ${title}` : `Chapter ${ceiling}`)
      )
    ),
    React.createElement("div", { className: "slider-wrap" },
      React.createElement("input", {
        type: "range", className: "slider", min, max: Math.max(max, min), value: ceiling,
        step: 1, disabled: max <= min,
        onChange: e => setCeiling(+e.target.value),
        "aria-label": "Chapter ceiling",
      }),
      React.createElement("span", { className: "chapnum" }, `${ceiling}/${max}`)
    ),
    React.createElement("div", { className: "ceiling-stat" },
      React.createElement("b", null, revealed), " entities revealed"
    )
  );
}

const CONTEXT_NAV = [
  { id: "novel", label: "Contents", icon: "book" },
  { id: "browse", label: "Codex", icon: "compass" },
  { id: "ask", label: "Ask", icon: "sparkles" },
];

function App({ user, onLogout, onUserUpdate }) {
  const [theme, setTheme] = useState(() => localStorage.getItem("nw-theme") || "light");
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  const [route, setRoute] = useState({ view: "library", params: {} });
  const [novelId, setNovelId] = useState(null);
  const [novel, setNovel] = useState(null);     // novel detail
  const [ceiling, setCeiling] = useState(1);
  const [stats, setStats] = useState(null);
  const debCeiling = useDebounce(ceiling, 250);

  const loadNovel = useCallback((id) => {
    return window.API.novel(id).then(n => {
      setNovel(n);
      const def = (n.progress && n.progress.max_chapter_read) || n.min_chapter || 1;
      setCeiling(c => (id === novelId ? c : def));  // keep ceiling when reloading the same novel
      return n;
    });
  }, [novelId]);

  // Load (or reload) the open novel's detail.
  useEffect(() => {
    if (novelId == null) { setNovel(null); setStats(null); return; }
    let cancel = false;
    window.API.novel(novelId).then(n => {
      if (cancel) return;
      setNovel(n);
      setCeiling((n.progress && n.progress.max_chapter_read) || n.min_chapter || 1);
    }).catch(() => { if (!cancel) setNovel(null); });
    return () => { cancel = true; };
  }, [novelId]);

  // Codex aggregate stats as the ceiling moves (only meaningful once codex is built).
  useEffect(() => {
    if (novelId == null) { setStats(null); return; }
    let cancel = false;
    window.API.stats(novelId, debCeiling).then(s => { if (!cancel) setStats(s); }).catch(() => { if (!cancel) setStats(null); });
    return () => { cancel = true; };
  }, [novelId, debCeiling]);

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); localStorage.setItem("nw-theme", theme); }, [theme]);
  useEffect(() => { window.scrollTo({ top: 0 }); }, [route]);
  useEffect(() => {
    const r = document.documentElement.style;
    r.setProperty("--accent-h", t.accentHue);
    r.setProperty("--serif", t.headings === "Literary"
      ? '"Newsreader", Georgia, serif'
      : '"Hanken Grotesk", system-ui, sans-serif');
    const c = CORNERS[t.corners] || CORNERS.Rounded;
    r.setProperty("--radius", c[0] + "px");
    r.setProperty("--radius-sm", c[1] + "px");
    r.setProperty("--radius-lg", c[2] + "px");
  }, [t]);

  // ── navigation ──
  // Deep-linkable surfaces (profile/account/admin) sync to the URL hash so they can be
  // shared/reloaded; everything else clears the hash and routes via React state only.
  const clearHash = () => { if (window.location.hash) history.replaceState(null, "", window.location.pathname + window.location.search); };
  const openLibrary = () => { setNovelId(null); setRoute({ view: "library", params: {} }); clearHash(); };
  const openDiscover = () => { setNovelId(null); setRoute({ view: "discover", params: {} }); clearHash(); };
  const openImport = () => { setNovelId(null); setRoute({ view: "import", params: {} }); clearHash(); };
  const openNovel = (id) => { setNovelId(id); setRoute({ view: "novel", params: {} }); clearHash(); };
  const openReader = (number) => setRoute({ view: "reader", params: { number } });
  const openProfile = (username) => { setNovelId(null); setRoute({ view: "profile", params: { username } }); window.location.hash = "#/u/" + encodeURIComponent(username); };
  const openAccount = () => { setNovelId(null); setRoute({ view: "account", params: {} }); window.location.hash = "#/account"; };
  const openAdmin = () => { setNovelId(null); setRoute({ view: "admin", params: {} }); window.location.hash = "#/admin"; };
  const nav = (view, params = {}) => setRoute({ view, params });
  const setView = (view) => setRoute({ view, params: {} });
  const reloadNovel = () => { if (novelId != null) loadNovel(novelId); };

  // Hash routing for deep-linkable surfaces. Runs on load (direct link) and on back/forward.
  useEffect(() => {
    const onHash = () => {
      const raw = (window.location.hash || "").replace(/^#\/?/, "");
      const path = raw.split("?")[0];
      const parts = path.split("/");
      if (parts[0] === "u" && parts[1]) { setNovelId(null); setRoute({ view: "profile", params: { username: decodeURIComponent(parts[1]) } }); }
      else if (path === "account") { setNovelId(null); setRoute({ view: "account", params: {} }); }
      else if (path === "admin") { setNovelId(null); setRoute({ view: "admin", params: {} }); }
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Reader reports progress → reflect it locally so the codex ceiling follows reading.
  const onRead = (number) => {
    setNovel(n => n ? { ...n, progress: { ...n.progress, last_chapter: number, max_chapter_read: Math.max(n.progress?.max_chapter_read || 0, number) } } : n);
    setCeiling(c => Math.max(c, number));
  };

  const codexMeta = novel ? {
    title: novel.title, blurb: novel.description || "",
    min: novel.min_chapter || 1, max: novel.max_chapter || (novel.min_chapter || 1),
    totalChapters: novel.max_chapter || 1, count: novel.chapter_count,
  } : null;

  const inNovel = novelId != null;
  const showCeiling = inNovel && ["browse", "entity", "ask"].includes(route.view);

  let screen;
  if (route.view === "import") {
    screen = React.createElement(ImportView, { openNovel, openLibrary });
  } else if (route.view === "discover") {
    screen = React.createElement(Discover, { openNovel, openLibrary });
  } else if (route.view === "profile") {
    screen = React.createElement(Profile, { username: route.params.username, currentUser: user, openNovel, openLibrary, openAccount });
  } else if (route.view === "account") {
    screen = React.createElement(AccountPanel, { user, onUserUpdate, openLibrary, openProfile });
  } else if (route.view === "admin") {
    screen = React.createElement(Admin, { openLibrary, openNovel, currentUser: user });
  } else if (!inNovel || route.view === "library") {
    screen = React.createElement(Library, { openNovel, openImport, openDiscover });
  } else if (route.view === "novel") {
    screen = React.createElement(NovelDetail, { novelId, novel, reloadNovel, openReader, nav, openLibrary, user });
  } else if (route.view === "reader") {
    screen = React.createElement(Reader, { novelId, number: route.params.number, openReader, backToNovel: () => setView("novel"), onRead });
  } else if (route.view === "browse") {
    screen = React.createElement(Browser, { novelId, ceiling, meta: codexMeta, nav });
  } else if (route.view === "entity") {
    screen = React.createElement(EntityPage, { novelId, id: route.params.id, ceiling, meta: codexMeta, nav, setView });
  } else if (route.view === "ask") {
    screen = React.createElement(Ask, { novelId, ceiling, initial: route.params.q });
  }

  const isReader = route.view === "reader";

  return React.createElement(CiteProvider, null,
    React.createElement("div", { className: "app" + (isReader ? " app-reader" : "") },
      React.createElement("header", { className: "appbar" },
        React.createElement("a", { className: "brand", onClick: openLibrary, style: { cursor: "pointer" } },
          React.createElement("div", { className: "brand-mark" }, React.createElement(Icon, { name: "book", size: 20 })),
          React.createElement("div", { className: "brand-name" },
            React.createElement("span", { className: "brand-title" }, "Tideglass"),
            React.createElement("span", { className: "brand-sub" }, "Library")
          )
        ),
        inNovel && React.createElement("nav", { className: "nav" },
          React.createElement("button", { className: "nav-tab", onClick: openLibrary, title: "Back to library" },
            React.createElement(Icon, { name: "arrowLeft", size: 16, sw: 2 }), "Library"),
          CONTEXT_NAV.map(n => React.createElement("button", {
            key: n.id,
            className: `nav-tab ${route.view === n.id || (n.id === "browse" && route.view === "entity") || (n.id === "novel" && route.view === "reader") ? "active" : ""}`,
            onClick: () => setView(n.id),
          }, React.createElement(Icon, { name: n.icon, size: 16, sw: 2 }), n.label))
        ),
        React.createElement("div", { className: "appbar-right" },
          inNovel && novel && React.createElement("span", { className: "appbar-novel muted", title: novel.title }, novel.title),
          React.createElement("button", {
            className: "icon-btn", onClick: () => setTheme(th => th === "light" ? "dark" : "light"),
            "aria-label": "Toggle theme",
          }, React.createElement(Icon, { name: theme === "light" ? "moon" : "sun", size: 18 })),
          user && React.createElement(UserMenu, { user, onLogout, onProfile: openProfile, onAccount: openAccount, onAdmin: openAdmin })
        )
      ),
      showCeiling && React.createElement(CeilingBar, { ceiling, setCeiling, meta: codexMeta, stats }),
      screen,
      React.createElement(TweaksPanel, { title: "Tweaks" },
        React.createElement(TweakSection, { label: "Accent" }),
        React.createElement(TweakRow, { label: "Colour" },
          React.createElement(AccentSwatches, { value: t.accentHue, onChange: v => setTweak("accentHue", v) })
        ),
        React.createElement(TweakSection, { label: "Style" }),
        React.createElement(TweakRadio, {
          label: "Headings", value: t.headings, options: ["Literary", "Modern"],
          onChange: v => setTweak("headings", v),
        }),
        React.createElement(TweakRadio, {
          label: "Corners", value: t.corners, options: ["Soft", "Rounded", "Sharp"],
          onChange: v => setTweak("corners", v),
        }),
        React.createElement(TweakSection, { label: "Theme" }),
        React.createElement(TweakRadio, {
          label: "Mode", value: theme, options: ["light", "dark"],
          onChange: v => setTheme(v),
        })
      )
    )
  );
}

/* AuthGate: resolve the session on load. Anonymous → AuthScreen; signed-in → the app.
   A mid-session 401 (expired cookie) routes back to the login screen via window.__onUnauthorized. */
function Root() {
  const [state, setState] = useState({ loading: true, user: null });

  useEffect(() => {
    let cancel = false;
    window.API.auth.me()
      .then(u => { if (!cancel) setState({ loading: false, user: u }); })
      .catch(() => { if (!cancel) setState({ loading: false, user: null }); });
    window.__onUnauthorized = () => setState(s => s.user ? { loading: false, user: null } : s);
    return () => { cancel = true; window.__onUnauthorized = null; };
  }, []);

  if (state.loading) {
    return React.createElement("div", { className: "auth-wrap" },
      React.createElement("div", { className: "muted" }, "Loading…"));
  }
  if (!state.user) {
    return React.createElement(AuthScreen, {
      onAuthed: (u) => { window.location.hash = ""; setState({ loading: false, user: u }); },
    });
  }
  return React.createElement(App, {
    user: state.user,
    onLogout: () => setState({ loading: false, user: null }),
    onUserUpdate: (u) => setState((s) => ({ ...s, user: u })),
  });
}

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(Root));
