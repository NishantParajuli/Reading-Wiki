/* Entity page — codex entry, facts, relationships, timeline, identity
   reveals. All data arrives pre-bounded from the server (chapter ≤ ceiling). */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { codexApi } from "../../modules/codex/api.js";
import { portraitLabel } from "../../modules/codex/presentation.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, EntityAvatar, Loading, TypeBadge } from "../../components/ui.jsx";
import { Markdown } from "../../lib/markdown.jsx";
import { CeilingControl } from "./CeilingControl.jsx";
import { useDebounce, useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";

function FactRow({ fact }) {
  return (
    <div className="fact">
      <div className="fact-chap">ch. {fmtChapter(fact.ch)}</div>
      <div className="grow">
        <div className="fact-type">{fact.type || "fact"}</div>
        <div className="fact-text">{fact.text}</div>
      </div>
    </div>
  );
}

export function EntityPage() {
  const { novel, novelId, ceiling, codexMeta } = useNovel();
  const { entityId: id } = useParams();
  const navigate = useNavigate();
  const debCeiling = useDebounce(ceiling, 250);
  const [status, setStatus] = useState("loading");
  const [profile, setProfile] = useState(null);
  const [rels, setRels] = useState([]);
  const [tl, setTl] = useState([]);
  const [idl, setIdl] = useState([]);
  const [errMsg, setErrMsg] = useState("");
  useTitle(profile ? profile.canonical_name : "Codex", novel.title);

  useEffect(() => {
    let cancel = false;
    setStatus("loading");
    (async () => {
      try {
        const p = await codexApi.entityProfile(novelId, id, debCeiling);
        if (cancel) return;
        setProfile(p);
        const [r, t, i] = await Promise.all([
          codexApi.relationships(novelId, id, debCeiling).catch(() => []),
          codexApi.timeline(novelId, id, debCeiling).catch(() => []),
          codexApi.identities(novelId, id, debCeiling).catch(() => []),
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
  }, [novelId, id, debCeiling]);

  const back = (
    <Button variant="ghost" size="sm" icon="arrowLeft" onClick={() => navigate(`/n/${novelId}/codex`)}>Codex</Button>
  );

  if (status === "loading") {
    return <div className="page page-enter">{back}<Loading label="Synthesizing the codex entry…" /></div>;
  }
  if (status === "notfound") {
    return (
      <div className="page page-enter">
        {back}
        <div style={{ marginTop: 16 }}>
          <EmptyState icon="lock" title="This entity hasn't appeared yet"
            body={`It is first seen in a chapter beyond ${fmtChapter(ceiling)}. Read further to reveal it.`} />
        </div>
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="page page-enter">
        {back}
        <div style={{ marginTop: 16 }}><EmptyState icon="x" title="Couldn't load this entry" body={errMsg} /></div>
      </div>
    );
  }

  const entity = {
    id: profile.id, name: profile.canonical_name, type: profile.type,
    firstSeen: profile.first_seen_chapter, blurb: profile.description || "",
    portrait: portraitLabel(profile.type, profile.canonical_name),
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

  const bookMax = codexMeta && (codexMeta.bookMax == null ? codexMeta.max : codexMeta.bookMax);
  const moreToCome = codexMeta && (bookMax == null || ceiling < bookMax);

  return (
    <div className="page page-enter">
      <div className="row wrap" style={{ justifyContent: "space-between" }}>
        {back}
        <CeilingControl />
      </div>

      <div className="entity-head" style={{ marginTop: 16 }}>
        <EntityAvatar entity={entity} lg />
        <div className="meta">
          <TypeBadge type={entity.type} />
          <h1 className="entity-title">{entity.name}</h1>
          <div className="alias-row">
            <Chip className="mono">first seen · ch. {fmtChapter(entity.firstSeen)}</Chip>
            {aliases.map((a, i) => <Chip key={i}>“{a}”</Chip>)}
          </div>
          <p className="entity-lede">{desc}</p>
        </div>
      </div>

      {idl.map((l, i) => (
        <div key={i} className="card id-banner">
          <Icon name="link" size={18} style={{ color: "var(--ok)" }} />
          <div style={{ flex: 1, minWidth: 200 }}>
            <b className="serif" style={{ fontSize: "var(--text-lg)" }}>Identity revealed</b>
            <div style={{ fontSize: "var(--text-md)", color: "var(--ink-2)", marginTop: 2 }}>
              {l.note || `Revealed to be the same as ${l.other_name}.`}{" "}
              <span className="muted">(ch. {fmtChapter(l.revealed_at_chapter)})</span>
            </div>
          </div>
          <Button variant="ghost" size="sm" iconRight="arrowRight"
                  onClick={() => navigate(`/n/${novelId}/codex/e/${l.other_id}`)}>
            View {l.other_name}
          </Button>
        </div>
      ))}

      <div className="entity-layout">
        <div>
          {profile.rendered_md && (
            <div className="card codex-entry">
              <p className="section-eyebrow">Codex entry</p>
              <Markdown text={profile.rendered_md} />
            </div>
          )}

          <div className="card" style={{ padding: "8px 24px" }}>
            <p className="section-eyebrow" style={{ margin: "18px 0 4px" }}>What's known · ch. ≤ {fmtChapter(ceiling)}</p>
            {knownFacts.length === 0
              ? <p className="muted" style={{ padding: "14px 0" }}>No recorded facts at this chapter yet.</p>
              : knownFacts.map((f, i) => <FactRow key={"k" + i} fact={f} />)}
          </div>

          {relItems.length > 0 && (
            <div style={{ marginTop: 26 }}>
              <p className="section-eyebrow">Relationships</p>
              <div className="card" style={{ padding: 10 }}>
                {relItems.map((r, i) => (
                  <button key={i} className={"rel " + (r.withType ? "t-" + r.withType : "")}
                          onClick={() => r.withId && navigate(`/n/${novelId}/codex/e/${r.withId}`)}>
                    <EntityAvatar entity={{ type: r.withType || "concept", portrait: "" }} />
                    <div className="grow">
                      <div className="rel-type">{r.type}</div>
                      <div className="rel-name">{r.withName || "Unknown"}</div>
                      {r.note && <div className="rel-note">{r.note}</div>}
                    </div>
                    <Chip className="mono">ch. {fmtChapter(r.ch)}</Chip>
                    <Icon name="arrowRight" size={16} className="muted" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <aside>
          <div className="card side-card">
            <h4><Icon name="clock" size={13} /> Timeline</h4>
            <div className="timeline">
              {tl.length === 0 && <div className="tl-text muted">No timeline yet at this chapter.</div>}
              {tl.map((t, i) => (
                <div key={i} className="tl-item">
                  <div className="tl-dot" />
                  <div className="tl-chap">Chapter {fmtChapter(t.chapter)}</div>
                  <div className="tl-text">{t.content}</div>
                </div>
              ))}
              {moreToCome && (
                <div className="tl-item" style={{ opacity: 0.6 }}>
                  <div className="tl-dot" style={{ background: "var(--border-2)" }} />
                  <div className="tl-chap">More to come</div>
                  <div className="tl-text">Hidden until you read further.</div>
                </div>
              )}
            </div>
          </div>
          <Button variant="ghost" full icon="sparkles" style={{ marginTop: 14 }}
                  onClick={() => navigate(`/n/${novelId}/ask?q=${encodeURIComponent(`Tell me about ${entity.name}.`)}`)}>
            Ask about {entity.name.split(" ")[0]}
          </Button>
        </aside>
      </div>
    </div>
  );
}
