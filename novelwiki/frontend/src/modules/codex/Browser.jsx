/* Codex browser — searchable entries scoped to the current chapter boundary.
   Knowledge beyond the boundary lies "under the tide": entries surface (with a
   ripple of light) when the boundary rises, and a frosted depth panel at the
   end stands in for everything still hidden. Stale lists vanish instantly —
   there is deliberately no exit animation for boundary-scoped content. */
import React, { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { codexApi } from "./api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, EntityAvatar, TypeBadge } from "../../components/ui.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { motion, springs } from "../../motion/index.js";
import { CeilingControl } from "./CeilingControl.jsx";
import { useDebounce, useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";
import { coverageLabel, monogramName } from "./presentation.js";
import { claimMorph, TideOrb, Ticker } from "./parts.jsx";

const FILTERS = [
  { id: "all", label: "All", icon: "layers" },
  { id: "character", label: "Characters", icon: "user" },
  { id: "location", label: "Places", icon: "mapPin" },
  { id: "faction", label: "Factions", icon: "users" },
  { id: "organization", label: "Organizations", icon: "users", optional: true },
  { id: "item", label: "Items", icon: "gem" },
  { id: "concept", label: "Concepts", icon: "spark" },
];
const ORG = "organization";

function EntityCard({ entity, index, surfacing, surfaceIndex, to, ceiling }) {
  const desc = entity.blurb || "No description recorded yet.";
  const orbRef = useRef(null);
  return (
    <Link to={to} state={{ codexEntity: { id: entity.id, name: entity.name, type: entity.type, ceiling }, codexMorph: true }}
          className={`cx-card t-${entity.type} ${surfacing ? "cx-surfacing" : "rise"}`}
          style={surfacing ? { "--si": surfaceIndex } : { "--i": Math.min(index, 14) }}
          onClick={() => claimMorph(orbRef.current)}
          data-spotlight="">
      <span className="cx-card-tint" aria-hidden="true" />
      <div className="cx-card-head">
        <span className="cx-orb" ref={orbRef}>
          <EntityAvatar entity={{ ...entity, name: monogramName(entity.name) }} />
          {surfacing && <span className="cx-ripple" aria-hidden="true"><i /><i /></span>}
        </span>
        <div className="cx-card-titles">
          <h3 className="cx-card-name">{entity.name}</h3>
          <span className="cx-card-tags">
            <TypeBadge type={entity.type} />
            {surfacing && <span className="cx-new"><Icon name="sparkles" size={11} sw={2} /> New</span>}
          </span>
        </div>
      </div>
      <p className="cx-card-desc">{desc}</p>
      <div className="cx-card-foot">
        <span className="cx-first-seen">First seen <b>Ch. {fmtChapter(entity.firstSeen)}</b></span>
        <span className="cx-card-go" aria-hidden="true"><Icon name="arrowRight" size={15} sw={2} /></span>
      </div>
    </Link>
  );
}

/* Organizations only appear as a filter when the book has some (they are rarer
   than the other types); the pill stays while it is the one selected. */
function FilterPills({ value, onChange, withOrgs }) {
  const group = useId();
  const shown = FILTERS.filter(f => !f.optional || withOrgs || value === f.id);
  return (
    <div className="cx-filters" role="group" aria-label="Filter entries by type">
      {shown.map(f => {
        const on = value === f.id;
        return (
          <button key={f.id} type="button" aria-pressed={on} className={"cx-filter" + (on ? " active" : "")} onClick={() => onChange(f.id)}>
            {on && <motion.span layoutId={`cx-filter-${group}`} className="cx-filter-lozenge" transition={springs.layout} aria-hidden="true" />}
            <Icon name={f.icon} size={14} sw={2} />
            <span>{f.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="cx-loading">
      <p className="cx-loading-label" role="status"><span className="spinner" aria-hidden="true" />Opening the codex…</p>
      <div className="cx-grid" aria-hidden="true">
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="cx-card cx-card-skeleton" style={{ "--i": i }}>
            <div className="cx-card-head">
              <span className="skeleton cx-sk-orb" />
              <div className="cx-card-titles"><span className="skeleton text" style={{ width: "70%" }} /><span className="skeleton text" style={{ width: "38%", height: 18 }} /></div>
            </div>
            <span className="skeleton text" style={{ width: "96%" }} />
            <span className="skeleton text" style={{ width: "74%" }} />
          </div>
        ))}
      </div>
    </div>
  );
}

/* The tide line and what lies beneath it. Decorative silhouettes only — it
   never implies how many entries are hidden. */
function Depths({ ceiling, readTo, novelId }) {
  return (
    <section className="cx-depths" aria-labelledby="cx-depths-title">
      <div className="cx-waterline" aria-hidden="true">
        <svg viewBox="0 0 1200 24" preserveAspectRatio="none" className="cx-waterline-wave">
          <path d="M0 12 C 50 4, 100 4, 150 12 S 250 20, 300 12 S 400 4, 450 12 S 550 20, 600 12 S 700 4, 750 12 S 850 20, 900 12 S 1000 4, 1050 12 S 1150 20, 1200 12" />
        </svg>
        <span className="cx-waterline-tag"><Icon name="wave" size={13} /> Tide line · Ch. {fmtChapter(ceiling)}</span>
      </div>
      <div className="cx-depths-panel">
        <div className="cx-depths-ghosts" aria-hidden="true">
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="cx-ghost" style={{ "--g": i }}>
              <span className="cx-ghost-orb" />
              <span className="redact"><span style={{ width: "72%" }} /><span style={{ width: "44%" }} /></span>
              <span className="redact"><span /><span style={{ width: "62%" }} /></span>
            </div>
          ))}
        </div>
        <div className="cx-depths-copy">
          <span className="cx-depths-lock" aria-hidden="true"><Icon name="lock" size={18} /></span>
          <h2 id="cx-depths-title" className="cx-depths-title">Still under the tide</h2>
          <p>Discoveries beyond chapter {fmtChapter(ceiling)} stay hidden until you read further.</p>
          {readTo != null && (
            <Link className="btn btn-ghost sm cx-depths-cta" to={`/n/${novelId}/read/${readTo}`}>
              <Icon name="bookOpen" size={14} /> Continue reading
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}

function Ledger({ stats }) {
  const items = [
    ["Entries", stats.entities_revealed],
    ["Facts", stats.facts_known],
    ["Connections", stats.relationships_known],
  ].filter(([, value]) => typeof value === "number" && Number.isFinite(value));
  if (!items.length) return null;
  return (
    <dl className="cx-ledger rise" style={{ "--i": 4 }}>
      {items.map(([label, value]) => (
        <div key={label} className="cx-ledger-item">
          <dt>{label}</dt>
          <dd><Ticker value={value} rise /></dd>
        </div>
      ))}
    </dl>
  );
}

export function CodexBrowser() {
  const { novel, novelId, ceiling, stats, codexMeta } = useNovel();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [list, setList] = useState(null);
  const [revealed, setRevealed] = useState(() => new Set());
  const [error, setError] = useState(null);
  const [loadedKey, setLoadedKey] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  const [hasOrgs, setHasOrgs] = useState(false);
  useTitle("Codex", novel.title);

  const debQ = useDebounce(q, 300);
  const debCeiling = useDebounce(ceiling, 250);
  const requestKey = JSON.stringify([novelId, debCeiling, debQ, filter]);
  // The last list the reader actually saw (and its boundary). "Newly revealed"
  // is measured against that — never against a response that was superseded
  // before it could be shown (e.g. the layout's initial boundary settling).
  const seen = useRef(null);

  useEffect(() => {
    let cancel = false;
    setList(null);
    setError(null);
    const type = filter === "all" ? null : filter;
    codexApi.listEntities(novelId, debCeiling, { type, q: debQ.trim() || null })
      .then(rows => {
        if (cancel) return;
        // The whole list at this boundary says whether organizations exist;
        // a narrower search can only confirm that some do.
        const orgs = rows.some(r => r.type === ORG);
        if (!type && !debQ.trim()) setHasOrgs(orgs);
        else if (!type && orgs) setHasOrgs(true);
        const sorted = [...rows].sort((a, b) => a.name.localeCompare(b.name));
        const newIds = new Set(sorted.map(r => r.id));
        const last = seen.current;
        const raised = last != null && debCeiling > last.ceiling;
        if (raised && last.ids.size > 0) {
          setRevealed(new Set([...newIds].filter(id => !last.ids.has(id))));
        } else {
          setRevealed(new Set());
        }
        setList(sorted);
        setLoadedKey(requestKey);
      })
      .catch(error => {
        if (!cancel) { setError(error.message || "Could not load the codex."); setLoadedKey(requestKey); }
      });
    return () => { cancel = true; };
  }, [novelId, debCeiling, debQ, filter, retryKey]);

  const isCurrent = loadedKey === requestKey && ceiling === debCeiling;
  const visibleList = isCurrent ? list : null;
  const visibleError = isCurrent ? error : null;

  useEffect(() => {
    if (visibleList) seen.current = { ceiling: debCeiling, ids: new Set(visibleList.map(entity => entity.id)) };
  }, [visibleList, debCeiling]);

  const bookMax = codexMeta && (codexMeta.bookMax == null ? codexMeta.max : codexMeta.bookMax);
  const showTeaser = !q.trim() && filter === "all" && (codexMeta && (bookMax == null || ceiling < bookMax));
  const builtThrough = stats && stats.built_through_chapter;
  const coverage = coverageLabel(stats, bookMax);
  const statsCurrent = stats != null && stats.effective_ceiling != null && Number(stats.effective_ceiling) === Number(ceiling);
  const filtered = q.trim() || filter !== "all";
  const readTo = novel.progress && (novel.progress.last_chapter ?? novel.progress.max_chapter_read);
  let surfaceCount = 0;

  return (
    <div className="page cx-page cx-browser page-enter">
      <header className="cx-hero">
        <div className="cx-hero-copy">
          <p className="section-eyebrow cx-eyebrow rise"><Icon name="compass" size={13} sw={2} /> Spoiler-safe codex</p>
          <h1 className="cx-title">
            <TextReveal text="The" />{" "}
            <TextReveal text="Codex" className="cx-title-em" delay={80} />
          </h1>
          <p className="cx-sub rise" style={{ "--i": 3 }}>
            People, places, and discoveries from <em>{novel.title}</em>, never beyond your chapter.
          </p>
          {statsCurrent && <Ledger stats={stats} />}
        </div>
        <div className="cx-hero-side">
          {codexMeta && bookMax != null && (
            <TideOrb ceiling={fmtChapter(ceiling)} min={fmtChapter(codexMeta.min || 1)} bookMax={fmtChapter(bookMax)}
                     readTo={codexMeta.max != null ? fmtChapter(codexMeta.max) : undefined} />
          )}
          <div className="cx-hero-controls rise" style={{ "--i": 3 }}>
            <CeilingControl />
            <Chip className="codex-build-coverage" tone={stats && builtThrough == null ? "warn" : "info"}
                  icon={builtThrough == null ? "clock" : "database"} role="status">
              {coverage}
            </Chip>
          </div>
        </div>
      </header>

      <div className="cx-toolbar rise" style={{ "--i": 5 }}>
        <div className="search-box cx-search">
          <Icon name="search" size={18} />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search characters, places, aliases…"
                 aria-label="Search the codex" type="search" enterKeyHint="search" />
          {q && <button type="button" className="icon-btn plain" aria-label="Clear" onClick={() => setQ("")}><Icon name="x" size={13} /></button>}
        </div>
        <FilterPills value={filter} onChange={setFilter} withOrgs={hasOrgs} />
      </div>

      {visibleError && <EmptyState icon="alert" title="The codex couldn't load" body={visibleError}
        primaryAction={<Button variant="secondary" icon="refresh" onClick={() => setRetryKey(key => key + 1)}>Try again</Button>} />}
      {visibleList == null && !visibleError && <SkeletonGrid />}

      {visibleList && visibleList.length === 0 && (
        <EmptyState icon={filtered ? "search" : "book"}
          title={filtered ? "No matches" : "Your story is still unfolding"}
          body={filtered ? "Try another name or a different category within your chapter boundary." : "Entries appear here once your chapters have been added to the codex. Your chapter boundary keeps later discoveries hidden."}
          primaryAction={filtered ? <Button variant="ghost" onClick={() => { setQ(""); setFilter("all"); }}>Clear filters</Button> : undefined} />
      )}

      {visibleList && visibleList.length > 0 && (
        <section className="cx-results" aria-labelledby="cx-results-title">
          <div className="cx-results-head">
            <h2 id="cx-results-title" className="cx-results-title">
              <Ticker value={visibleList.length} /> {visibleList.length === 1 ? "entry" : "entries"}
            </h2>
            <span className="cx-results-meta">A–Z · known through Ch. {fmtChapter(ceiling)}</span>
            {revealed.size > 0 && (
              <span className="cx-results-new"><Icon name="sparkles" size={12} sw={2} /> {revealed.size} newly revealed</span>
            )}
          </div>
          <div className="cx-grid">
            {visibleList.map((e, i) => {
              const surfacing = revealed.has(e.id);
              return (
                <EntityCard key={e.id} entity={e} index={i} ceiling={ceiling}
                            surfacing={surfacing} surfaceIndex={surfacing ? surfaceCount++ : 0}
                            to={`/n/${novelId}/codex/e/${e.id}`} />
              );
            })}
          </div>
        </section>
      )}

      {visibleList && visibleList.length > 0 && showTeaser && (
        <Depths ceiling={ceiling} readTo={readTo} novelId={novelId} />
      )}
    </div>
  );
}
