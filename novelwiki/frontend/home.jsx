/* ============================================================
   Home surface (backend-driven)
   ============================================================ */
function Home({ ceiling, meta, stats, nav, setView }) {
  const debCeiling = useDebounce(ceiling, 250);
  const [recent, setRecent] = useState(null); // null = loading
  const SAMPLE_Q = "Who is the most important character so far?";

  useEffect(() => {
    let cancel = false;
    setRecent(null);
    window.API.listEntities(debCeiling)
      .then(list => {
        if (cancel) return;
        const sorted = [...list].sort((a, b) => b.firstSeen - a.firstSeen).slice(0, 6);
        setRecent(sorted);
      })
      .catch(() => { if (!cancel) setRecent([]); });
    return () => { cancel = true; };
  }, [debCeiling]);

  const total = (meta && meta.totalChapters) || 1;
  const pct = stats ? stats.pct_read : Math.round((ceiling / total) * 100);
  const ceilingTitle = stats && stats.ceiling_title;
  const num = (v) => (stats == null ? "—" : v);

  return React.createElement("div", { className: "page" },
    // hero
    React.createElement("div", { className: "hero" },
      React.createElement("div", { className: "card hero-card" },
        React.createElement("div", { className: "hero-eyebrow" },
          React.createElement(Icon, { name: "book", size: 14 }), "The Codex · Spoiler-safe"
        ),
        React.createElement("h1", null, (meta && meta.title) || "Codex"),
        React.createElement("p", null, (meta && meta.blurb) || ""),
        React.createElement("div", { className: "row", style: { gap: 14, marginBottom: 10 } },
          React.createElement("span", { className: "chip mono" }, `ch. ${ceiling} / ${total}`),
          React.createElement("span", { className: "muted", style: { fontSize: 13.5 } },
            ceilingTitle ? `“${ceilingTitle}”` : "in progress"
          )
        ),
        React.createElement("div", { className: "progress-track" },
          React.createElement("div", { className: "progress-fill", style: { width: pct + "%" } })
        ),
        React.createElement("div", { className: "row", style: { marginTop: 22, gap: 10 } },
          React.createElement("button", { className: "btn btn-primary", onClick: () => setView("browse") },
            React.createElement(Icon, { name: "compass", size: 17 }), "Explore the codex"
          ),
          React.createElement("button", { className: "btn btn-ghost", onClick: () => setView("ask") },
            React.createElement(Icon, { name: "sparkles", size: 17 }), "Ask a question"
          )
        )
      ),
      // ask promo
      React.createElement("div", { className: "card ask-promo" },
        React.createElement("div", { className: "hero-eyebrow", style: { color: "var(--sage)" } },
          React.createElement(Icon, { name: "shield", size: 14 }), "Nothing past ch. " + ceiling
        ),
        React.createElement("h3", null, "Ask anything — safely."),
        React.createElement("p", { className: "muted", style: { fontSize: 14, lineHeight: 1.55, margin: 0 } },
          "Every answer is grounded in cited evidence and bounded to what you've actually read."
        ),
        React.createElement("button", { className: "ask-mini", onClick: () => setView("ask") },
          React.createElement(Icon, { name: "search", size: 16 }),
          React.createElement("span", { className: "grow", style: { textAlign: "left" } }, SAMPLE_Q),
          React.createElement(Icon, { name: "arrowRight", size: 16 })
        )
      )
    ),

    // stats
    React.createElement("div", { className: "stat-row" },
      React.createElement(Stat, { num: num(stats && stats.entities_revealed), label: "Entities revealed" }),
      React.createElement(Stat, { num: num(stats && stats.facts_known), label: "Facts known", sage: true }),
      React.createElement(Stat, { num: num(stats && stats.relationships_known), label: "Relationships mapped" }),
      React.createElement(Stat, { num: stats == null ? "—" : pct + "%", label: "Of the story read" })
    ),

    // recently unlocked
    React.createElement("p", { className: "section-eyebrow" },
      recent && recent.length ? "Recently revealed" : "Begin reading to reveal entities"
    ),
    recent == null
      ? React.createElement(SkeletonGrid, { count: 6 })
      : React.createElement("div", { className: "grid grid-entities" },
          recent.map(e => React.createElement(EntityCard, { key: e.id, entity: e, ceiling, nav })),
          recent.length === 0 && React.createElement("div", { className: "muted", style: { gridColumn: "1/-1", padding: 20 } },
            "Nothing has been revealed at this chapter yet. Slide the chapter control above, or run the ingestion pipeline from Admin."
          )
        )
  );
}

function Stat({ num, label, sage, lock }) {
  return React.createElement("div", { className: "card stat" },
    React.createElement("div", { className: `stat-num ${sage ? "sage" : ""}`, style: lock ? { color: "var(--muted)" } : null }, num),
    React.createElement("div", { className: "stat-label" }, label)
  );
}

window.Home = Home;
