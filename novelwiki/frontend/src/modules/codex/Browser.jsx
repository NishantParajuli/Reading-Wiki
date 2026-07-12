/* Codex browser (§6.8) — search + type filters, reveal-flash entity grid,
   decorative teaser row. Server only ever returns entities ≤ ceiling. */
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { codexApi } from "../../modules/codex/api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Chip, EmptyState, EntityAvatar, TypeBadge } from "../../components/ui.jsx";
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

/* Decorative-only "to come" card: holds no real data beyond the ceiling. */
function TeaserCard() {
  return (
    <div className="ecard locked t-concept" aria-hidden>
      <div className="ecard-top">
        <div className="avatar t-concept"><div className="ph" /></div>
        <div className="grow">
          <div className="redact" style={{ maxWidth: 130 }}><span style={{ width: "80%", height: 13 }} /></div>
        </div>
      </div>
      <div className="redact"><span style={{ width: "100%" }} /><span style={{ width: "55%" }} /></div>
      <div className="ecard-foot">
        <span className="lock-pill"><Icon name="lock" size={12} className="lk" /> Revealed as you read on</span>
      </div>
    </div>
  );
}

function SkeletonGrid({ count = 8 }) {
  return (
    <div className="grid grid-entities">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="ecard skeleton-card t-concept" aria-hidden>
          <div className="ecard-top">
            <div className="avatar t-concept"><div className="ph" /></div>
            <div className="redact" style={{ maxWidth: 130 }}><span style={{ width: "80%", height: 13 }} /></div>
          </div>
          <div className="redact"><span style={{ width: "100%" }} /><span style={{ width: "55%" }} /></div>
        </div>
      ))}
    </div>
  );
}

export function CodexBrowser() {
  const { novel, novelId, ceiling, codexMeta } = useNovel();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [list, setList] = useState(null);
  const [revealed, setRevealed] = useState(() => new Set());
  useTitle("Codex", novel.title);

  const debQ = useDebounce(q, 300);
  const debCeiling = useDebounce(ceiling, 250);
  const prevIds = useRef(new Set());
  const prevCeiling = useRef(debCeiling);

  useEffect(() => {
    let cancel = false;
    setList(null);
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
      })
      .catch(() => { if (!cancel) setList([]); });
    return () => { cancel = true; };
  }, [novelId, debCeiling, debQ, filter]);

  const bookMax = codexMeta && (codexMeta.bookMax == null ? codexMeta.max : codexMeta.bookMax);
  const showTeaser = !q.trim() && filter === "all" && (codexMeta && (bookMax == null || ceiling < bookMax));

  return (
    <div className="page page-enter">
      <div className="codex-head">
        <div>
          <p className="section-eyebrow" style={{ margin: 0 }}>The Codex</p>
          <h1 className="page-title">{novel.title}</h1>
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
          <button key={f.id} className={`filter ${filter === f.id ? "active" : ""}`} onClick={() => setFilter(f.id)}>
            <Icon name={f.icon} size={14} sw={2} /> {f.label}
          </button>
        ))}
      </div>

      {list == null && <SkeletonGrid count={8} />}

      {list && list.length === 0 && !showTeaser && (
        <EmptyState icon="search" title="No matches" body="Nothing in the chapters you've read matches that." />
      )}

      {list && list.length > 0 && (
        <div className="grid grid-entities">
          {list.map(e => (
            <EntityCard key={e.id} entity={e} justRevealed={revealed.has(e.id)}
                        onOpen={() => navigate(`/n/${novelId}/codex/e/${e.id}`)} />
          ))}
        </div>
      )}

      {list && showTeaser && (
        <>
          <p className="section-eyebrow" style={{ marginTop: 38 }}>
            <Icon name="lock" size={12} style={{ marginRight: 6, verticalAlign: "-1px" }} /> Not yet revealed
          </p>
          <div className="grid grid-entities"><TeaserCard /></div>
          <p className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 12 }}>
            Hidden by the spoiler boundary — these reveal themselves as you read further.
          </p>
        </>
      )}
    </div>
  );
}
