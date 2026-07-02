/* ============================================================
   Entity browser + EntityCard (shared, backend-driven)

   The server only ever returns entities first-seen <= ceiling, so there are no
   "locked" entity cards with real data. The reveal animation is preserved by
   detecting entities that newly appear when the ceiling is raised. The "Not yet
   revealed" strip below is a purely decorative teaser — it is fed NO real data
   (no names, no chapters, no count), so nothing about future chapters leaks.
   ============================================================ */
function EntityCard({ entity, ceiling, nav, justRevealed }) {
  const desc = entity.blurb || "No description recorded yet.";
  return React.createElement("button", {
    className: `ecard t-${entity.type} ${justRevealed ? "flash just-revealed" : ""}`,
    onClick: () => nav("entity", { id: entity.id }),
  },
    React.createElement("div", { className: "ecard-top" },
      React.createElement(Avatar, { entity }),
      React.createElement("div", { style: { minWidth: 0, flex: 1 } },
        React.createElement("div", { className: "ecard-name" }, entity.name),
        React.createElement("div", { style: { marginTop: 9 } },
          React.createElement(TypeBadge, { type: entity.type })
        )
      )
    ),
    React.createElement("p", { className: "ecard-desc" }, desc),
    React.createElement("div", { className: "ecard-foot" },
      React.createElement("span", { className: "chip mono" }, `first seen · ch. ${entity.firstSeen}`),
      React.createElement(Icon, { name: "arrowRight", size: 16, className: "muted", style: { marginLeft: "auto" } })
    )
  );
}

// Decorative-only "to come" card. Holds no data; exists to honor the design's
// redaction aesthetic without sending anything from beyond the ceiling.
function TeaserCard({ k }) {
  return React.createElement("div", { className: "ecard locked t-concept", key: k, "aria-hidden": true },
    React.createElement("div", { className: "ecard-top" },
      React.createElement("div", { className: "avatar t-concept" }, React.createElement("div", { className: "ph" })),
      React.createElement("div", { className: "grow" },
        React.createElement("div", { className: "redact", style: { maxWidth: 130 } },
          React.createElement("span", { style: { width: "80%", height: 13 } })
        )
      )
    ),
    React.createElement("div", { className: "redact" },
      React.createElement("span", { style: { width: "100%" } }),
      React.createElement("span", { style: { width: "55%" } })
    ),
    React.createElement("div", { className: "ecard-foot" },
      React.createElement("span", { className: "lock-pill" },
        React.createElement(Icon, { name: "lock", size: 12, className: "lk" }),
        "Revealed as you read on"
      )
    )
  );
}

const FILTERS = [
  { id: "all", label: "All", icon: "layers" },
  { id: "character", label: "Characters", icon: "user" },
  { id: "location", label: "Places", icon: "mapPin" },
  { id: "faction", label: "Factions", icon: "users" },
  { id: "item", label: "Items", icon: "gem" },
  { id: "concept", label: "Concepts", icon: "spark" },
];

function Browser({ novelId, ceiling, meta, nav }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [list, setList] = useState(null); // null = loading
  const [revealed, setRevealed] = useState(() => new Set());

  const debQ = useDebounce(q, 300);
  const debCeiling = useDebounce(ceiling, 250);
  const prevIds = useRef(new Set());
  const prevCeiling = useRef(debCeiling);

  useEffect(() => {
    let cancel = false;
    setList(null);
    const type = filter === "all" ? null : filter;
    window.API.listEntities(novelId, debCeiling, { type, q: debQ.trim() || null })
      .then(rows => {
        if (cancel) return;
        const sorted = [...rows].sort((a, b) => a.name.localeCompare(b.name));
        const newIds = new Set(sorted.map(r => r.id));
        const raised = debCeiling > prevCeiling.current;
        if (raised && prevIds.current.size > 0) {
          setRevealed(new Set([...newIds].filter(id => !prevIds.current.has(id))));
        } else {
          setRevealed(new Set());
        }
        prevCeiling.current = debCeiling;
        prevIds.current = newIds;
        setList(sorted);
      })
      .catch(() => { if (!cancel) setList([]); });
    return () => { cancel = true; };
  }, [debCeiling, debQ, filter]);

  const bookMax = meta && (meta.bookMax == null ? meta.max : meta.bookMax);
  const showTeaser = !q.trim() && filter === "all" &&
    (meta && (bookMax == null || ceiling < bookMax));

  return React.createElement("div", { className: "page" },
    React.createElement("p", { className: "section-eyebrow" }, "The Codex"),
    React.createElement("div", { className: "browse-head" },
      React.createElement("div", { className: "search-box" },
        React.createElement(Icon, { name: "search", size: 18, className: "muted" }),
        React.createElement("input", {
          value: q, onChange: e => setQ(e.target.value),
          placeholder: "Search characters, places, aliases…",
        }),
        q && React.createElement("button", { className: "icon-btn", style: { width: 28, height: 28 }, onClick: () => setQ("") },
          React.createElement(Icon, { name: "x", size: 14 }))
      )
    ),
    React.createElement("div", { className: "filters", style: { marginBottom: 24 } },
      FILTERS.map(f => React.createElement("button", {
        key: f.id, className: `filter ${filter === f.id ? "active" : ""}`, onClick: () => setFilter(f.id),
      }, React.createElement(Icon, { name: f.icon, size: 14, sw: 2 }), f.label))
    ),

    list == null && React.createElement(SkeletonGrid, { count: 8 }),

    list && list.length === 0 && !showTeaser &&
      React.createElement(EmptyState, {
        icon: "search", title: "No matches",
        body: "Nothing in the chapters you've read matches that.",
      }),

    list && list.length > 0 && React.createElement("div", { className: "grid grid-entities" },
      list.map(e => React.createElement(EntityCard, { key: e.id, entity: e, ceiling, nav, justRevealed: revealed.has(e.id) }))
    ),

    list && showTeaser && React.createElement(React.Fragment, null,
      React.createElement("p", { className: "section-eyebrow", style: { marginTop: 38 } },
        React.createElement(Icon, { name: "lock", size: 12, style: { marginRight: 6, verticalAlign: "-1px" } }),
        "Not yet revealed"
      ),
      React.createElement("div", { className: "grid grid-entities" },
        [0, 1, 2].map(i => React.createElement(TeaserCard, { key: "teaser" + i, k: "teaser" + i }))
      ),
      React.createElement("p", { className: "muted", style: { fontSize: 12.5, marginTop: 12 } },
        "Hidden by the spoiler boundary — these reveal themselves as you read further."
      )
    )
  );
}

Object.assign(window, { EntityCard, Browser });
