/* ============================================================
   App shell — ceiling bar, theme, router, tweaks (backend-driven)
   ============================================================ */
const NAV = [
  { id: "home", label: "Home", icon: "book" },
  { id: "browse", label: "Codex", icon: "compass" },
  { id: "ask", label: "Ask", icon: "sparkles" },
];

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
        React.createElement("span", { className: "ceiling-eyebrow" }, "Reading through"),
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

function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("nw-theme") || "light");
  const [ceiling, setCeiling] = useState(() => +(localStorage.getItem("nw-ceiling") || 1));
  const [route, setRoute] = useState({ view: "home", params: {} });
  const [meta, setMeta] = useState(null);
  const [stats, setStats] = useState(null);
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);

  const debCeiling = useDebounce(ceiling, 250);

  // Load novel meta once; clamp the saved ceiling into the available range.
  useEffect(() => {
    let cancel = false;
    window.API.meta()
      .then(m => {
        if (cancel) return;
        const min = m.min_chapter != null ? m.min_chapter : 1;
        const max = m.max_chapter != null ? m.max_chapter : min;
        const normalized = { title: m.novel_title, blurb: m.novel_blurb, count: m.count, min, max, totalChapters: max };
        setMeta(normalized);
        window.NOVEL.meta = { title: m.novel_title, blurb: m.novel_blurb, totalChapters: max };
        setCeiling(c => Math.min(Math.max(c, min), max));
      })
      .catch(() => {
        if (cancel) return;
        setMeta({ title: "Codex", blurb: "", count: 0, min: 1, max: 1, totalChapters: 1 });
      });
    return () => { cancel = true; };
  }, []);

  // Refresh spoiler-safe aggregate stats (+ ceiling title) as the ceiling moves.
  useEffect(() => {
    let cancel = false;
    window.API.stats(debCeiling)
      .then(s => { if (!cancel) setStats(s); })
      .catch(() => { if (!cancel) setStats(null); });
    return () => { cancel = true; };
  }, [debCeiling]);

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); localStorage.setItem("nw-theme", theme); }, [theme]);
  useEffect(() => { localStorage.setItem("nw-ceiling", ceiling); }, [ceiling]);
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

  const setView = (view) => setRoute({ view, params: {} });
  const nav = (view, params = {}) => setRoute({ view, params });

  let screen;
  if (route.view === "home") screen = React.createElement(Home, { ceiling, meta, stats, nav, setView });
  else if (route.view === "browse") screen = React.createElement(Browser, { ceiling, meta, nav });
  else if (route.view === "entity") screen = React.createElement(EntityPage, { id: route.params.id, ceiling, meta, nav, setView });
  else if (route.view === "ask") screen = React.createElement(Ask, { ceiling, initial: route.params.q });
  else if (route.view === "admin") screen = React.createElement(Admin, { setView });

  return React.createElement(CiteProvider, null,
    React.createElement("div", { className: "app" },
      React.createElement("header", { className: "appbar" },
        React.createElement("a", { className: "brand", onClick: () => setView("home"), style: { cursor: "pointer" } },
          React.createElement("div", { className: "brand-mark" }, React.createElement(Icon, { name: "book", size: 20 })),
          React.createElement("div", { className: "brand-name" },
            React.createElement("span", { className: "brand-title" }, "Tideglass"),
            React.createElement("span", { className: "brand-sub" }, "Codex")
          )
        ),
        React.createElement("nav", { className: "nav" },
          NAV.map(n => React.createElement("button", {
            key: n.id, className: `nav-tab ${route.view === n.id || (n.id === "browse" && route.view === "entity") ? "active" : ""}`,
            onClick: () => setView(n.id),
          }, React.createElement(Icon, { name: n.icon, size: 16, sw: 2 }), n.label))
        ),
        React.createElement("div", { className: "appbar-right" },
          React.createElement("button", {
            className: `icon-btn ${route.view === "admin" ? "active" : ""}`, onClick: () => setView("admin"),
            title: "Admin · ingestion pipeline", "aria-label": "Admin",
          }, React.createElement(Icon, { name: "database", size: 18 })),
          React.createElement("button", {
            className: "icon-btn", onClick: () => setTheme(th => th === "light" ? "dark" : "light"),
            "aria-label": "Toggle theme",
          }, React.createElement(Icon, { name: theme === "light" ? "moon" : "sun", size: 18 }))
        )
      ),
      React.createElement(CeilingBar, { ceiling, setCeiling, meta, stats }),
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

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));
