/* Searchable codex entries scoped to the current chapter boundary. */
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { codexApi } from "../../modules/codex/api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, EntityAvatar, Loading, TypeBadge } from "../../components/ui.jsx";
import { CeilingControl } from "./CeilingControl.jsx";
import { useDebounce, useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";

const FILTERS = [
  { id: "all", label: "All", icon: "layers" },
  { id: "character", label: "Characters", icon: "user" },
  { id: "location", label: "Places", icon: "mapPin" },
  { id: "faction", label: "Factions", icon: "users" },
  { id: "item", label: "Items", icon: "gem" },
  { id: "concept", label: "Concepts", icon: "spark" },
];

function EntityCard({ entity, justRevealed, onOpen }) {
  const desc = entity.blurb || "No description recorded yet.";
  return (
    <button className={`ecard t-${entity.type} ${justRevealed ? "flash just-revealed" : ""}`} onClick={onOpen}>
      <div className="ecard-top">
        <EntityAvatar entity={entity} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="ecard-name">{entity.name}</div>
          <div style={{ marginTop: 9 }}><TypeBadge type={entity.type} /></div>
        </div>
      </div>
      <p className="ecard-desc">{desc}</p>
      <div className="ecard-foot">
        <Chip className="mono">first seen · ch. {fmtChapter(entity.firstSeen)}</Chip>
        <Icon name="arrowRight" size={16} className="muted" style={{ marginLeft: "auto" }} />
      </div>
    </button>
  );
}

export function CodexBrowser() {
  const { novel, novelId, ceiling, stats, codexMeta } = useNovel();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [list, setList] = useState(null);
  const [revealed, setRevealed] = useState(() => new Set());
  const [error, setError] = useState(null);
  const [loadedKey, setLoadedKey] = useState(null);
  const [retryKey, setRetryKey] = useState(0);
  useTitle("Codex", novel.title);

  const debQ = useDebounce(q, 300);
  const debCeiling = useDebounce(ceiling, 250);
  const requestKey = JSON.stringify([novelId, debCeiling, debQ, filter]);
  const prevIds = useRef(new Set());
  const prevCeiling = useRef(debCeiling);

  useEffect(() => {
    let cancel = false;
    setList(null);
    setError(null);
    const type = filter === "all" ? null : filter;
    codexApi.listEntities(novelId, debCeiling, { type, q: debQ.trim() || null })
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

  const bookMax = codexMeta && (codexMeta.bookMax == null ? codexMeta.max : codexMeta.bookMax);
  const showTeaser = !q.trim() && filter === "all" && (codexMeta && (bookMax == null || ceiling < bookMax));
  const builtThrough = stats && stats.built_through_chapter;
  const builtCount = stats && Number(stats.built_chapter_count || 0);
  const bookExtent = bookMax != null ? ` of ${fmtChapter(bookMax)}` : "";
  const builtCountLabel = builtCount
    ? ` · ${builtCount} chapter${builtCount === 1 ? "" : "s"}`
    : "";
  const coverageLabel = stats == null
    ? "Checking build coverage…"
    : builtThrough == null
      ? "Codex not built yet"
      : `Built through Ch. ${fmtChapter(builtThrough)}${bookExtent}${builtCountLabel}`;

  return (
    <div className="page page-enter">
      <div className="codex-head">
        <div>
          <h1 className="page-title">The Codex</h1>
          <p className="muted" style={{ margin: "6px 0 14px" }}>People, places, and discoveries from {novel.title}.</p>
          <Chip className="codex-build-coverage" tone={stats && builtThrough == null ? "warn" : "info"}
                icon={builtThrough == null ? "clock" : "database"} role="status">
            {coverageLabel}
          </Chip>
        </div>
        <div style={{ marginLeft: "auto" }}><CeilingControl /></div>
      </div>

      <div className="codex-head" style={{ marginBottom: 14 }}>
        <div className="search-box">
          <Icon name="search" size={17} className="muted" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search characters, places, aliases…"
                 aria-label="Search the codex" />
          {q && <button className="icon-btn plain" style={{ width: 26, height: 26 }} aria-label="Clear" onClick={() => setQ("")}><Icon name="x" size={13} /></button>}
        </div>
      </div>
      <div className="filters" style={{ marginBottom: 24 }}>
        {FILTERS.map(f => (
          <button key={f.id} aria-pressed={filter === f.id} className={`filter ${filter === f.id ? "active" : ""}`} onClick={() => setFilter(f.id)}>
            <Icon name={f.icon} size={14} sw={2} /> {f.label}
          </button>
        ))}
      </div>

      {visibleError && <EmptyState icon="alert" title="The codex couldn't load" body={visibleError}
        primaryAction={<Button variant="secondary" onClick={() => setRetryKey(key => key + 1)}>Try again</Button>} />}
      {visibleList == null && !visibleError && <Loading label="Opening the codex…" />}

      {visibleList && visibleList.length === 0 && (
        <EmptyState icon={q.trim() || filter !== "all" ? "search" : "book"}
          title={q.trim() || filter !== "all" ? "No matches" : "Your story is still unfolding"}
          body={q.trim() || filter !== "all" ? "Try another name or a different category within your chapter boundary." : "Entries appear here once your chapters have been added to the codex. Your chapter boundary keeps later discoveries hidden."}
          primaryAction={q.trim() || filter !== "all" ? <Button variant="ghost" onClick={() => { setQ(""); setFilter("all"); }}>Clear filters</Button> : undefined} />
      )}

      {visibleList && visibleList.length > 0 && (
        <div className="grid grid-entities">
          {visibleList.map(e => (
            <EntityCard key={e.id} entity={e} justRevealed={revealed.has(e.id)}
                        onOpen={() => navigate(`/n/${novelId}/codex/e/${e.id}`)} />
          ))}
        </div>
      )}

      {visibleList && visibleList.length > 0 && showTeaser && (
        <p className="muted" style={{ fontSize: "var(--text-sm)", marginTop: 28 }}>
          <Icon name="lock" size={14} style={{ marginRight: 6, verticalAlign: "-2px" }} />
          Discoveries beyond chapter {fmtChapter(ceiling)} stay hidden until you read further.
        </p>
      )}
    </div>
  );
}
