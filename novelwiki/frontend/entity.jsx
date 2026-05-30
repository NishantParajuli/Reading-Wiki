/* ============================================================
   Entity page — codex entry, facts, relationships, timeline, identity reveals
   All data arrives pre-bounded from the server (chapter <= ceiling).
   ============================================================ */
function EntityPage({ id, ceiling, meta, nav, setView }) {
  const debCeiling = useDebounce(ceiling, 250);
  const [status, setStatus] = useState("loading"); // loading | ok | notfound | error
  const [profile, setProfile] = useState(null);
  const [rels, setRels] = useState([]);
  const [tl, setTl] = useState([]);
  const [idl, setIdl] = useState([]);
  const [errMsg, setErrMsg] = useState("");

  useEffect(() => {
    let cancel = false;
    setStatus("loading");
    (async () => {
      try {
        const p = await window.API.entityProfile(id, debCeiling);
        if (cancel) return;
        setProfile(p);
        const [r, t, i] = await Promise.all([
          window.API.relationships(id, debCeiling).catch(() => []),
          window.API.timeline(id, debCeiling).catch(() => []),
          window.API.identities(id, debCeiling).catch(() => []),
        ]);
        if (cancel) return;
        setRels(r || []); setTl(t || []); setIdl(i || []);
        setStatus("ok");
      } catch (e) {
        if (cancel) return;
        if (e.status === 404) setStatus("notfound");
        else { setErrMsg(e.message || "Failed to load."); setStatus("error"); }
      }
    })();
    return () => { cancel = true; };
  }, [id, debCeiling]);

  if (status === "loading") {
    return React.createElement("div", { className: "page" },
      React.createElement(BackBtn, { setView }),
      React.createElement(Loading, { label: "Synthesizing the codex entry…" })
    );
  }

  if (status === "notfound") {
    return React.createElement("div", { className: "page" },
      React.createElement(BackBtn, { setView }),
      React.createElement("div", { className: "notfound", style: { marginTop: 16 } },
        React.createElement(Icon, { name: "lock", size: 22, className: "muted" }),
        React.createElement("div", null,
          React.createElement("b", { style: { fontSize: 16 } }, "This entity hasn't appeared yet"),
          React.createElement("div", { className: "muted", style: { fontSize: 14, marginTop: 4 } },
            `It is first seen in a chapter beyond ${ceiling}. Read further to reveal it.`)
        )
      )
    );
  }

  if (status === "error") {
    return React.createElement("div", { className: "page" },
      React.createElement(BackBtn, { setView }),
      React.createElement("div", { className: "notfound", style: { marginTop: 16 } },
        React.createElement(Icon, { name: "x", size: 22, className: "muted" }),
        React.createElement("div", null,
          React.createElement("b", { style: { fontSize: 16 } }, "Couldn't load this entry"),
          React.createElement("div", { className: "muted", style: { fontSize: 14, marginTop: 4 } }, errMsg)
        )
      )
    );
  }

  const entity = {
    id: profile.id, name: profile.canonical_name, type: profile.type,
    firstSeen: profile.first_seen_chapter, blurb: profile.description || "",
    portrait: window.portraitLabel(profile.type, profile.canonical_name),
  };
  const knownFacts = (profile.facts || []).map(f => ({ id: f.id, ch: f.chapter, type: f.fact_type, text: f.content }));
  const aliases = profile.aliases || [];
  const desc = knownFacts.length ? knownFacts[knownFacts.length - 1].text : entity.blurb;
  const linkedSet = new Set([profile.id, ...(profile.linked_personas || [])]);

  const relItems = (rels || []).map(r => {
    const isSource = linkedSet.has(r.source_id);
    return {
      id: r.id,
      withId: isSource ? r.target_id : r.source_id,
      withName: isSource ? r.target_name : r.source_name,
      withType: isSource ? r.target_type : r.source_type,
      type: r.relation_type,
      ch: r.chapter,
      note: r.content,
    };
  });

  const moreToCome = meta && (meta.max == null || ceiling < meta.max);

  return React.createElement("div", { className: "page" },
    React.createElement(BackBtn, { setView }),

    React.createElement("div", { className: "entity-head", style: { marginTop: 16 } },
      React.createElement(Avatar, { entity, lg: true }),
      React.createElement("div", { className: "meta" },
        React.createElement(TypeBadge, { type: entity.type }),
        React.createElement("h1", { className: "entity-title" }, entity.name),
        React.createElement("div", { className: "alias-row" },
          React.createElement("span", { className: "chip mono" }, `first seen · ch. ${entity.firstSeen}`),
          aliases.map((a, i) => React.createElement("span", { key: i, className: "chip" }, `“${a}”`))
        ),
        React.createElement("p", { style: { fontSize: 16.5, lineHeight: 1.6, color: "var(--ink-2)", marginTop: 16, maxWidth: "54ch" } }, desc)
      )
    ),

    // identity reveal banners
    idl.map((l, i) =>
      React.createElement("div", { key: i, className: "card id-banner" },
        React.createElement(Icon, { name: "link", size: 18, style: { color: "var(--sage)" } }),
        React.createElement("div", { style: { flex: 1 } },
          React.createElement("b", { className: "serif", style: { fontSize: 16 } }, "Identity revealed"),
          React.createElement("div", { style: { fontSize: 14, color: "var(--ink-2)", marginTop: 2 } },
            l.note || `Revealed to be the same as ${l.other_name}.`, " ",
            React.createElement("span", { className: "muted" }, `(ch. ${l.revealed_at_chapter})`)
          )
        ),
        React.createElement("button", { className: "btn btn-ghost", style: { padding: "8px 14px" }, onClick: () => nav("entity", { id: l.other_id }) },
          "View ", l.other_name, React.createElement(Icon, { name: "arrowRight", size: 15 }))
      )
    ),

    React.createElement("div", { className: "entity-layout" },
      // main column
      React.createElement("div", null,
        profile.rendered_md && React.createElement("div", { className: "card codex-entry" },
          React.createElement("p", { className: "section-eyebrow" }, "Codex entry"),
          React.createElement(Markdown, { text: profile.rendered_md })
        ),

        React.createElement("div", { className: "card", style: { padding: "8px 24px" } },
          React.createElement("p", { className: "section-eyebrow", style: { margin: "18px 0 4px" } },
            `What's known · ch. ≤ ${ceiling}`),
          knownFacts.length === 0
            ? React.createElement("p", { className: "muted", style: { padding: "14px 0" } }, "No recorded facts at this chapter yet.")
            : knownFacts.map((f, i) => React.createElement(FactRow, { key: "k" + i, fact: f }))
        ),

        relItems.length > 0 && React.createElement("div", { style: { marginTop: 26 } },
          React.createElement("p", { className: "section-eyebrow" }, "Relationships"),
          React.createElement("div", { className: "card", style: { padding: 10 } },
            relItems.map((r, i) =>
              React.createElement("div", {
                key: i, className: "rel " + (r.withType ? "t-" + r.withType : ""),
                onClick: () => r.withId && nav("entity", { id: r.withId }),
              },
                React.createElement(Avatar, { entity: { type: r.withType || "concept", portrait: "" } }),
                React.createElement("div", { className: "grow" },
                  React.createElement("div", { className: "rel-type" }, r.type),
                  React.createElement("div", { className: "rel-name" }, r.withName || "Unknown"),
                  r.note && React.createElement("div", { className: "rel-note" }, r.note)
                ),
                React.createElement("span", { className: "chip mono" }, `ch. ${r.ch}`),
                React.createElement(Icon, { name: "arrowRight", size: 16, className: "muted" })
              )
            )
          )
        )
      ),

      // sidebar
      React.createElement("aside", null,
        React.createElement("div", { className: "card side-card" },
          React.createElement("h4", null, React.createElement(Icon, { name: "clock", size: 13, style: { verticalAlign: "-2px", marginRight: 6 } }), "Timeline"),
          React.createElement("div", { className: "timeline" },
            tl.length === 0 && React.createElement("div", { className: "tl-text muted" }, "No timeline yet at this chapter."),
            tl.map((t, i) => React.createElement("div", { key: i, className: "tl-item" },
              React.createElement("div", { className: "tl-dot" }),
              React.createElement("div", { className: "tl-chap" }, `Chapter ${t.chapter}`),
              React.createElement("div", { className: "tl-text" }, t.content)
            )),
            moreToCome && React.createElement("div", { className: "tl-item", style: { opacity: 0.6 } },
              React.createElement("div", { className: "tl-dot", style: { background: "var(--border-2)" } }),
              React.createElement("div", { className: "tl-chap" }, "More to come"),
              React.createElement("div", { className: "tl-text" }, "Hidden until you read further.")
            )
          )
        ),
        React.createElement("button", { className: "btn btn-ghost", style: { width: "100%", marginTop: 14 }, onClick: () => nav("ask", { q: `Tell me about ${entity.name}.` }) },
          React.createElement(Icon, { name: "sparkles", size: 16 }), "Ask about ", entity.name.split(" ")[0]
        )
      )
    )
  );
}

function FactRow({ fact }) {
  return React.createElement("div", { className: "fact" },
    React.createElement("div", { className: "fact-chap" }, "ch. " + fact.ch),
    React.createElement("div", { className: "fact-body" },
      React.createElement("div", { className: "fact-type" }, fact.type || "fact"),
      React.createElement("div", { className: "fact-text" }, fact.text)
    )
  );
}

function BackBtn({ setView }) {
  return React.createElement("button", { className: "btn btn-ghost", style: { padding: "8px 14px" }, onClick: () => setView("browse") },
    React.createElement(Icon, { name: "arrowLeft", size: 16 }), "Codex"
  );
}

window.EntityPage = EntityPage;
