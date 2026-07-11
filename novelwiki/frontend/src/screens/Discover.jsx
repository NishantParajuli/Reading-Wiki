/* ============================================================
   Discover (§6.5) — shared library browse. Debounced live search, filter
   chips synced to the URL (?lang=ko&codex=1 shareable), load-more
   pagination, optimistic add-to-library.
   ============================================================ */
import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { catalogApi } from "../modules/catalog/api.js";
import { experienceApi } from "../modules/experience/api.js";
import { Icon } from "../components/Icon.jsx";
import { Button, Chip, Cover, EmptyState, Loading, PageHeader } from "../components/ui.jsx";
import { Popover, MenuItem } from "../components/overlay.jsx";
import { useToast } from "../components/toast.jsx";
import { useDebounce, useTitle } from "../lib/hooks.js";
import { STATUS_TAG_LABELS, STATUS_TAG_ORDER, TRANSLATION_TYPE_LABELS } from "../lib/constants.js";

const PAGE = 60;

const LANGS = [["en", "English"], ["ja", "Japanese"], ["ko", "Korean"], ["zh", "Chinese"]];
const TRANSLATIONS = [["translated", "Translated"], ["raws", "Raws"], ["raws+translated", "Raws + Translated"]];
const FRESHNESS = [["fresh_7d", "Scraped in 7 days"], ["fresh_30d", "Scraped in 30 days"], ["stale_30d", "Stale 30+ days"], ["never_scraped", "Never scraped"]];
const SORTS = [["recent", "Recently updated"], ["fresh", "Freshest source"], ["title", "Title (A–Z)"]];

function FilterMenu({ label, value, options, onChange }) {
  const [open, setOpen] = useState(false);
  const selected = options.find(([v]) => v === value);
  return (
    <Popover open={open} onClose={() => setOpen(false)} align="left" trigger={
      <button className={"filter-chip" + (value ? " on" : "")} aria-expanded={open} onClick={() => setOpen(o => !o)}>
        {selected ? selected[1] : label}
        {value
          ? <span role="button" aria-label={`Clear ${label}`} onClick={(e) => { e.stopPropagation(); setOpen(false); onChange(""); }}
                  style={{ display: "inline-grid", placeItems: "center" }}><Icon name="x" size={12} sw={2.4} /></span>
          : <Icon name="chevronDown" size={13} />}
      </button>
    }>
      {options.map(([v, l]) => (
        <MenuItem key={v} selected={value === v} onClick={() => { setOpen(false); onChange(value === v ? "" : v); }}>{l}</MenuItem>
      ))}
    </Popover>
  );
}

function DiscoverCard({ n, onAdd, added }) {
  const meta = [
    n.chapter_count ? `${n.chapter_count} ch.` : null,
    n.owner_username ? `@${n.owner_username}` : null,
  ].filter(Boolean).join(" · ");
  return (
    <Link className="shelf-card" to={`/n/${n.id}`}>
      <span style={{ position: "relative", display: "block" }}>
        <Cover src={n.cover_url} title={n.title} />
        <button className={"disc-add" + (added ? " added" : "")} disabled={added}
                aria-label={added ? "In library" : `Add ${n.title} to library`}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (!added) onAdd(n); }}>
          <Icon name={added ? "check" : "plus"} size={13} sw={2.4} /> {added ? "In library" : "Add"}
        </button>
      </span>
      <span>
        <span className="shelf-card-title">{n.title}</span>
        {n.author && <span className="shelf-card-author" style={{ display: "block" }}>{n.author}</span>}
      </span>
      <span className="shelf-card-meta" style={{ flexWrap: "wrap", display: "flex", gap: 5 }}>
        {n.has_codex && <Chip tone="ok">Codex</Chip>}
        {n.has_audio && <Chip tone="ok">Audio</Chip>}
        {n.translation_type && <Chip tone="accent">{TRANSLATION_TYPE_LABELS[n.translation_type]}</Chip>}
      </span>
      {meta && <span className="rail-sub">{meta}</span>}
    </Link>
  );
}

export function Discover() {
  const [sp, setSp] = useSearchParams();
  const { toast } = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  useTitle("Discover");

  const [q, setQ] = useState(sp.get("q") || "");
  const debQ = useDebounce(q, 300);
  const filters = {
    language: sp.get("lang") || "",
    translation: sp.get("tr") || "",
    tag: sp.get("tag") || "",
    has_codex: sp.get("codex") === "1",
    has_audio: sp.get("audio") === "1",
    freshness: sp.get("fresh") || "",
    sort: sp.get("sort") || "recent",
  };

  const setParam = (key, v) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(key, v === true ? "1" : v); else next.delete(key);
    setSp(next, { replace: true });
  };

  // Keep ?q= in the URL in sync with the debounced search text.
  useEffect(() => { setParam("q", debQ.trim()); }, [debQ]); // eslint-disable-line react-hooks/exhaustive-deps

  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [addedIds, setAddedIds] = useState(() => new Set());

  const filterKey = useMemo(() => JSON.stringify({ debQ, ...filters }), [debQ, sp]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancel = false;
    setItems(null);
    experienceApi.discover({ q: debQ.trim(), ...filters, offset: 0, limit: PAGE }).then(r => {
      if (cancel) return;
      const list = Array.isArray(r) ? r : (r.items || []);
      setItems(list);
      setTotal(Array.isArray(r) ? list.length : (r.total ?? list.length));
    }).catch(() => { if (!cancel) { setItems([]); setTotal(0); } });
    return () => { cancel = true; };
  }, [filterKey]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadMore() {
    setLoadingMore(true);
    try {
      const r = await experienceApi.discover({ q: debQ.trim(), ...filters, offset: items.length, limit: PAGE });
      const list = Array.isArray(r) ? r : (r.items || []);
      setItems(prev => [...prev, ...list]);
      if (!Array.isArray(r) && r.total != null) setTotal(r.total);
    } catch (e) {
      toast(e.message || "Couldn't load more.", { tone: "danger" });
    } finally {
      setLoadingMore(false);
    }
  }

  /* Optimistic add: flips to "In library ✓" instantly, rolls back on failure. */
  async function add(n) {
    setAddedIds(prev => new Set(prev).add(n.id));
    try {
      await catalogApi.addToLibrary(n.id);
      qc.invalidateQueries({ queryKey: ["novels"] });
      toast(`Added “${n.title}” to your library.`, {
        tone: "ok",
        action: { label: "Open", onClick: () => navigate(`/n/${n.id}`) },
      });
    } catch (e) {
      setAddedIds(prev => { const s = new Set(prev); s.delete(n.id); return s; });
      toast(e.message || "Couldn't add it.", { tone: "danger" });
    }
  }

  const tagOptions = STATUS_TAG_ORDER.map(t => [t, STATUS_TAG_LABELS[t] || t]);

  return (
    <div className="page page-enter">
      <PageHeader title="Discover" subtitle="The shared library — add anything to read it with your own progress." />

      <div className="lib-toolbar">
        <div className="search-box" style={{ flex: "1 1 260px", maxWidth: 420 }}>
          <Icon name="search" size={16} className="muted" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search shared titles…" aria-label="Search the shared library" />
          {q && <button className="icon-btn plain" style={{ width: 26, height: 26 }} aria-label="Clear search" onClick={() => setQ("")}><Icon name="x" size={13} /></button>}
        </div>
      </div>

      <div className="disc-filters">
        <FilterMenu label="Language" value={filters.language} options={LANGS} onChange={v => setParam("lang", v)} />
        <FilterMenu label="Translation" value={filters.translation} options={TRANSLATIONS} onChange={v => setParam("tr", v)} />
        <FilterMenu label="Genre" value={filters.tag} options={tagOptions} onChange={v => setParam("tag", v)} />
        <FilterMenu label="Freshness" value={filters.freshness} options={FRESHNESS} onChange={v => setParam("fresh", v)} />
        <button className={"filter-chip" + (filters.has_codex ? " on" : "")} aria-pressed={filters.has_codex}
                onClick={() => setParam("codex", !filters.has_codex)}>
          <Icon name="compass" size={13} /> Has codex
        </button>
        <button className={"filter-chip" + (filters.has_audio ? " on" : "")} aria-pressed={filters.has_audio}
                onClick={() => setParam("audio", !filters.has_audio)}>
          <Icon name="headphones" size={13} /> Has audio
        </button>
        <div style={{ marginLeft: "auto" }}>
          {/* default sort renders as a plain menu, not an active/removable filter */}
          <FilterMenu label="Recently updated" value={filters.sort === "recent" ? "" : filters.sort}
                      options={SORTS.filter(([v]) => v !== "recent")}
                      onChange={v => setParam("sort", v)} />
        </div>
      </div>

      {items == null ? (
        <Loading label="Loading the shared library…" />
      ) : items.length === 0 ? (
        <EmptyState icon="compass" title="Nothing to discover" body="Global novels and other readers' public uploads show up here. Try clearing a filter." />
      ) : (
        <>
          <div className="lib-grid">
            {items.map(n => <DiscoverCard key={n.id} n={n} onAdd={add} added={addedIds.has(n.id)} />)}
          </div>
          {items.length < total && (
            <div className="load-more-row">
              <Button variant="ghost" loading={loadingMore} onClick={loadMore}>
                Load more ({items.length} of {total})
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
