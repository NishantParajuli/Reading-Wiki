/* Entity page — a dossier: codex entry, what's known (a tideline of facts),
   relationships (cards + a constellation drawn only from real relations),
   timeline, identity reveals. All data arrives pre-bounded from the server
   (chapter ≤ ceiling). While a request is pending nothing from a previous
   boundary is shown; the hero may show the name the reader just clicked, but
   only when it was listed at the very boundary still on screen. */
import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { codexApi } from "./api.js";
import { monogramName, portraitLabel } from "./presentation.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, EmptyState, EntityAvatar, TypeBadge } from "../../components/ui.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { Markdown } from "../../lib/markdown.jsx";
import { CeilingControl } from "./CeilingControl.jsx";
import { useDebounce, useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";
import { useMorphTarget } from "./parts.jsx";
import { Constellation, KnownTideline, RelationshipCards, Timeline } from "./EntityParts.jsx";

// "Ask about Mira" — but never "Ask about The".
function askName(name) {
  const first = String(name || "").split(" ")[0];
  return /^(the|a|an)$/i.test(first) ? name : first;
}

/* The hero keeps one stable DOM shape from loading to loaded, so the orb that
   flew in from the card (and the name already revealed) is never remounted. */
function Hero({ entity, profile, aliases = [], lede, orbRef, loading }) {
  return (
    <header className={"cx-dossier-hero" + (loading ? " is-loading" : "") + (entity ? ` t-${entity.type}` : "")}>
      <span className="cx-dossier-aura" aria-hidden="true" />
      <span className="cx-hero-orb" ref={orbRef}>
        {entity ? <EntityAvatar entity={{ ...entity, name: monogramName(entity.name) }} lg /> : <span className="skeleton cx-sk-orb-lg" aria-hidden="true" />}
      </span>
      <div className="cx-hero-meta">
        <div className="cx-hero-kicker">
          {entity ? <TypeBadge type={entity.type} /> : <span className="skeleton text" style={{ width: 96, height: 22 }} aria-hidden="true" />}
          {profile && <span className="cx-first-seen fade-in">First seen <b>Ch. {fmtChapter(profile.first_seen_chapter)}</b></span>}
        </div>
        {entity
          ? <TextReveal as="h1" className="cx-entity-name" text={entity.name} step={60} />
          : <span className="skeleton cx-sk-name" aria-hidden="true" />}
        {loading ? (
          <span className="skeleton text cx-sk-lede" aria-hidden="true" />
        ) : (
          <>
            {aliases.length > 0 && (
              <ul className="cx-aliases rise" style={{ "--i": 2 }} aria-label="Also known as">
                {aliases.map((a, i) => <li key={i} className="cx-alias">{a}</li>)}
              </ul>
            )}
            {lede && <p className="cx-lede rise" style={{ "--i": 3 }}>{lede}</p>}
          </>
        )}
      </div>
    </header>
  );
}

export function EntityPage() {
  const { novel, novelId, ceiling, setCeiling, codexMeta } = useNovel();
  const { entityId: id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const debCeiling = useDebounce(ceiling, 250);
  const [status, setStatus] = useState("loading");
  const [profile, setProfile] = useState(null);
  const [rels, setRels] = useState([]);
  const [tl, setTl] = useState([]);
  const [idl, setIdl] = useState([]);
  const [errMsg, setErrMsg] = useState("");
  const [loadedKey, setLoadedKey] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const requestKey = JSON.stringify([novelId, id, debCeiling]);
  const isCurrent = loadedKey === requestKey && ceiling === debCeiling;
  useTitle(isCurrent && profile ? profile.canonical_name : "Codex", novel.title);

  const navState = location.state || {};
  const seed = navState.codexEntity;
  const seedValid = Boolean(seed && String(seed.id) === String(id) && Number(seed.ceiling) === Number(ceiling));
  const orbRef = useMorphTarget(navState.codexMorph ? location.key : null);

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
        setLoadedKey(requestKey);
        setStatus("ok");
      } catch (e) {
        if (cancel) return;
        setLoadedKey(requestKey);
        if (e.status === 404) setStatus("notfound");
        else { setErrMsg(e.message || "Failed to load."); setStatus("error"); }
      }
    })();
    return () => { cancel = true; };
  }, [novelId, id, debCeiling, retryKey]);

  const top = (
    <div className="cx-dossier-top">
      <Button variant="ghost" size="sm" icon="arrowLeft" onClick={() => navigate(`/n/${novelId}/codex`)}>Codex</Button>
      <CeilingControl />
    </div>
  );

  if (status === "loading" || !isCurrent) {
    return (
      <div className="page cx-page cx-entity page-enter">
        {top}
        <Hero entity={seedValid ? { id: seed.id, name: seed.name, type: seed.type } : null} orbRef={orbRef} loading />
        <p className="cx-loading-label cx-dossier-status" role="status"><span className="spinner" aria-hidden="true" />Synthesizing the codex entry…</p>
        <div className="cx-dossier cx-dossier-pending" aria-hidden="true">
          <div className="cx-dossier-main">
            <div className="card cx-entry cx-entry-skeleton">
              {[92, 100, 84, 96, 58].map((w, i) => <span key={i} className="skeleton text" style={{ width: `${w}%` }} />)}
            </div>
          </div>
          <div className="cx-dossier-side"><div className="card cx-side-skeleton"><span className="skeleton text" style={{ width: "40%" }} /><span className="skeleton text" /><span className="skeleton text" style={{ width: "70%" }} /></div></div>
        </div>
      </div>
    );
  }
  if (status === "notfound") {
    const canRaise = codexMeta && Number(ceiling) < Number(codexMeta.max);
    return (
      <div className="page cx-page cx-entity page-enter">
        {top}
        <div className="cx-submerged">
          <EmptyState icon="lock" title="This entity hasn't appeared yet"
            body={`It is first seen in a chapter beyond ${fmtChapter(ceiling)}. Read further to reveal it.`}
            primaryAction={canRaise
              ? <Button variant="secondary" icon="wave" onClick={() => setCeiling(codexMeta.max)}>Show through Ch. {fmtChapter(codexMeta.max)}</Button>
              : <Button variant="ghost" icon="arrowLeft" onClick={() => navigate(`/n/${novelId}/codex`)}>Back to the Codex</Button>} />
        </div>
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="page cx-page cx-entity page-enter">
        {top}
        <div className="cx-submerged"><EmptyState icon="x" title="Couldn't load this entry" body={errMsg}
          primaryAction={<Button variant="secondary" icon="refresh" onClick={() => setRetryKey(key => key + 1)}>Try again</Button>} /></div>
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

  // Entry citations that name only a fact or relationship still point at a chapter.
  const citedChapter = new Map([
    ...knownFacts.map(f => [`fact:${f.id}`, f.ch]),
    ...relItems.map(r => [`rel:${r.id}`, r.ch]),
  ]);
  const chapterOf = (kind, citeId) => {
    const ch = citedChapter.get(`${kind}:${citeId}`);
    return ch == null ? null : fmtChapter(ch);
  };

  const bookMax = codexMeta && (codexMeta.bookMax == null ? codexMeta.max : codexMeta.bookMax);
  const moreToCome = codexMeta && (bookMax == null || ceiling < bookMax);
  const entityPath = (otherId) => `/n/${novelId}/codex/e/${otherId}`;
  const linkState = (other) => ({ codexEntity: { ...other, ceiling }, codexMorph: true });

  return (
    <div className="page cx-page cx-entity page-enter">
      {top}
      <Hero entity={entity} profile={profile} aliases={aliases} lede={desc} orbRef={orbRef} />

      {idl.map((l, i) => (
        <div key={i} className="cx-identity rise" style={{ "--i": 4 + i }}>
          <span className="cx-identity-orb" aria-hidden="true"><Icon name="link" size={18} sw={2} /></span>
          <div className="cx-identity-copy">
            <b>Identity revealed</b>
            <p>
              {l.note || `Revealed to be the same as ${l.other_name}.`}{" "}
              <span className="cx-identity-ch">(ch. {fmtChapter(l.revealed_at_chapter)})</span>
            </p>
          </div>
          <Button variant="ghost" size="sm" iconRight="arrowRight"
                  onClick={() => navigate(entityPath(l.other_id))}>
            View {l.other_name}
          </Button>
        </div>
      ))}

      <div className="cx-dossier">
        <div className="cx-dossier-main">
          {profile.rendered_md && (
            <section className={`card cx-entry t-${entity.type} rise`} style={{ "--i": 5 }} aria-labelledby="cx-entry-title">
              <header className="cx-panel-head">
                <h2 id="cx-entry-title" className="section-eyebrow"><Icon name="feather" size={13} sw={2} /> Codex entry</h2>
                <span className="cx-panel-note">As of Ch. {fmtChapter(ceiling)}</span>
              </header>
              <Markdown text={profile.rendered_md} className="prose cx-entry-prose" chapterOf={chapterOf} />
            </section>
          )}

          <KnownTideline facts={knownFacts} ceiling={ceiling} />

          {relItems.length > 0 && (
            <RelationshipCards items={relItems} pathFor={entityPath} stateFor={linkState} />
          )}
        </div>

        <aside className="cx-dossier-side">
          {relItems.length > 0 && (
            <Constellation entity={entity} items={relItems} onOpen={(rel) => rel.withId != null && navigate(entityPath(rel.withId))} />
          )}
          <Timeline items={tl} moreToCome={moreToCome} />
          <Link className="btn btn-ghost full cx-ask-about" to={`/n/${novelId}/ask?q=${encodeURIComponent(`Tell me about ${entity.name}.`)}`}>
            <Icon name="sparkles" size={16} />
            Ask about {askName(entity.name)}
          </Link>
        </aside>
      </div>
    </div>
  );
}
