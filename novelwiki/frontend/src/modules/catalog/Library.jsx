/* ============================================================
   Library (§6.4) — cover-forward bookshelf. Search, sort, grid/list toggle,
   shelf tabs, optimistic shelf moves with undo, add-novel dialog.
   ============================================================ */
import React, { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { catalogApi } from "../../modules/catalog/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Cover, EmptyState, Loading, PageHeader, ProgressBar, SegmentedControl, Tabs } from "../../components/ui.jsx";
import { Popover, MenuItem } from "../../components/overlay.jsx";
import { AddNovelDialog } from "./AddNovelDialog.jsx";
import { useToast } from "../../components/toast.jsx";
import { useNovelsQuery } from "../../modules/catalog/queries.js";
import { useLocalStorage, useTitle } from "../../lib/hooks.js";
import { SHELF_LABELS, SHELF_ORDER } from "../../lib/constants.js";
import { fmtChapter, relativeTime } from "../../lib/utils.js";

const LIBRARY_TABS = [
  { id: "all", label: "All" },
  { id: "reading", label: "Reading" },
  { id: "to_read", label: "To read" },
  { id: "completed", label: "Completed" },
];

const SORTS = [
  { id: "recent_read", label: "Recently read" },
  { id: "recent_updated", label: "Recently updated" },
  { id: "title", label: "Title" },
  { id: "progress", label: "Progress" },
];

const EMPTY_COPY = {
  all: { title: "No novels yet", body: "Add your first novel to start reading." },
  reading: { title: "Nothing on the go", body: "Open a book and it lands here." },
  to_read: { title: "The pile is empty", body: "Shelve something for later from a novel's page." },
  completed: { title: "Nothing finished yet", body: "The ending will come." },
};

function pct(n) {
  const max = n.max_chapter || 0;
  const read = n.max_chapter_read || 0;
  return max > 0 ? Math.round(Math.min(100, (read / max) * 100)) : 0;
}

function statusChip(n) {
  const started = n.last_chapter != null;
  if (n.new_chapters > 0) return <Chip tone="accent">{n.new_chapters} new</Chip>;
  if (n.shelf === "completed") return <Chip tone="ok">Finished</Chip>;
  if (started) return <Chip>Ch. {fmtChapter(n.last_chapter)}</Chip>;
  return null;
}

function ShelfMenu({ n, onMove, onRemove }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onClose={() => setOpen(false)} trigger={
      <button className="cover-action" aria-label="Shelf menu" aria-expanded={open}
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(o => !o); }}>
        <Icon name="more" size={16} sw={2.6} />
      </button>
    }>
      <div className="menu-label">Shelf</div>
      {SHELF_ORDER.map(s => (
        <MenuItem key={s} selected={n.shelf === s}
                  onClick={(e) => { e.preventDefault(); setOpen(false); onMove(n, n.shelf === s ? "" : s); }}>
          {SHELF_LABELS[s]}
        </MenuItem>
      ))}
      <div className="menu-sep" />
      <MenuItem icon="x" danger onClick={(e) => { e.preventDefault(); setOpen(false); onRemove(n); }}>
        Remove from library
      </MenuItem>
    </Popover>
  );
}

function GridCard({ n, onMove, onRemove }) {
  const navigate = useNavigate();
  const started = n.last_chapter != null;
  const resumeCh = started ? n.last_chapter : (n.min_chapter || 1);
  return (
    <Link className="shelf-card" to={`/n/${n.id}`}>
      <span style={{ position: "relative", display: "block" }}>
        <Cover src={n.cover_url} title={n.title} />
        <span className="cover-actions">
          {(n.chapter_count || 0) > 0 && (
            <button className="cover-action" aria-label={started ? "Resume" : "Start reading"}
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/n/${n.id}/read/${resumeCh}`); }}>
              <Icon name="play" size={15} />
            </button>
          )}
          <ShelfMenu n={n} onMove={onMove} onRemove={onRemove} />
        </span>
      </span>
      <span>
        <span className="shelf-card-title">{n.title}</span>
        {n.author && <span className="shelf-card-author" style={{ display: "block" }}>{n.author}</span>}
      </span>
      {started && pct(n) > 0 && <ProgressBar size="xs" value={pct(n)} />}
      <span className="shelf-card-meta">{statusChip(n)}</span>
    </Link>
  );
}

function ListRow({ n, onMove, onRemove }) {
  return (
    <Link className="lib-row" to={`/n/${n.id}`}>
      <Cover src={n.cover_url} title={n.title} />
      <span className="grow">
        <span className="lib-row-title" style={{ display: "block" }}>{n.title}</span>
        {n.author && <span className="lib-row-author">{n.author}</span>}
      </span>
      <ProgressBar size="xs" value={pct(n)} />
      <span className="lib-row-nums">
        {n.last_chapter != null ? `${fmtChapter(n.last_chapter)}/${fmtChapter(n.max_chapter || 0)}` : `${n.chapter_count} ch.`}
      </span>
      {n.shelf && <Chip>{SHELF_LABELS[n.shelf]}</Chip>}
      {n.last_read_at && <span className="muted" style={{ fontSize: "var(--text-xs)", flexShrink: 0 }}>{relativeTime(n.last_read_at)}</span>}
      <ShelfMenu n={n} onMove={onMove} onRemove={onRemove} />
    </Link>
  );
}

export function Library() {
  const { data: novels, isLoading } = useNovelsQuery();
  const qc = useQueryClient();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [tab, setTab] = useLocalStorage("nw-lib-tab", "all");
  const [view, setView] = useLocalStorage("nw-lib-view", "grid");
  const [sort, setSort] = useLocalStorage("nw-lib-sort", "recent_read");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  useTitle("Library");

  const all = novels || [];
  const counts = { all: all.length, reading: 0, to_read: 0, completed: 0 };
  all.forEach(n => { if (n.shelf && counts[n.shelf] != null) counts[n.shelf]++; });

  const shown = useMemo(() => {
    let list = tab === "all" ? all : all.filter(n => n.shelf === tab);
    const needle = q.trim().toLowerCase();
    if (needle) {
      list = list.filter(n => n.title.toLowerCase().includes(needle) || (n.author || "").toLowerCase().includes(needle));
    }
    const key = {
      recent_read: (a, b) => String(b.last_read_at || "").localeCompare(String(a.last_read_at || "")),
      recent_updated: (a, b) => String(b.source_updated_at || "").localeCompare(String(a.source_updated_at || "")),
      title: (a, b) => a.title.localeCompare(b.title),
      progress: (a, b) => pct(b) - pct(a),
    }[sort];
    return key ? [...list].sort(key) : list;
  }, [all, tab, q, sort]);

  /* Optimistic shelf move with rollback + undo toast. */
  async function moveShelf(n, shelf) {
    const prevShelf = n.shelf || "";
    qc.setQueryData(["novels"], (old) => (old || []).map(x => x.id === n.id ? { ...x, shelf: shelf || null } : x));
    try {
      await catalogApi.updateNovel(n.id, { shelf });
      toast(shelf ? `Moved to ${SHELF_LABELS[shelf]}.` : "Removed from shelf.", {
        tone: "ok",
        action: {
          label: "Undo",
          onClick: async () => {
            qc.setQueryData(["novels"], (old) => (old || []).map(x => x.id === n.id ? { ...x, shelf: prevShelf || null } : x));
            try { await catalogApi.updateNovel(n.id, { shelf: prevShelf }); } catch (e) { qc.invalidateQueries({ queryKey: ["novels"] }); }
          },
        },
      });
    } catch (e) {
      qc.setQueryData(["novels"], (old) => (old || []).map(x => x.id === n.id ? { ...x, shelf: prevShelf || null } : x));
      toast(e.message || "Couldn't change the shelf.", { tone: "danger" });
    }
  }

  async function removeFromLibrary(n) {
    qc.setQueryData(["novels"], (old) => (old || []).filter(x => x.id !== n.id));
    try {
      await catalogApi.removeFromLibrary(n.id);
      toast(`Removed “${n.title}” from your library. Progress is kept.`, {
        tone: "ok",
        action: {
          label: "Undo",
          onClick: async () => {
            try { await catalogApi.addToLibrary(n.id); } catch (e) { /* refetch below restores truth */ }
            qc.invalidateQueries({ queryKey: ["novels"] });
          },
        },
      });
    } catch (e) {
      qc.invalidateQueries({ queryKey: ["novels"] });
      toast(e.message || "Couldn't remove it.", { tone: "danger" });
    }
  }

  const emptyCopy = EMPTY_COPY[tab] || EMPTY_COPY.all;

  return (
    <div className="page page-enter">
      <PageHeader title="Library" subtitle="Everything you're reading, in one place."
        actions={
          <>
            <Button variant="ghost" icon="upload" onClick={() => navigate("/import")}>Import</Button>
            <Button variant="primary" icon="sparkles" onClick={() => setAdding(true)}>Add novel</Button>
          </>
        } />

      <div className="lib-toolbar">
        <div className="search-box">
          <Icon name="search" size={16} className="muted" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search your library…" aria-label="Search your library" />
          {q && <button className="icon-btn plain" style={{ width: 26, height: 26 }} aria-label="Clear search" onClick={() => setQ("")}><Icon name="x" size={13} /></button>}
        </div>
        <select className="shelf-select" value={sort} onChange={e => setSort(e.target.value)} aria-label="Sort by" style={{ padding: "8px 10px" }}>
          {SORTS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
        <SegmentedControl fit ariaLabel="View" value={view} onChange={setView}
          options={[{ value: "grid", icon: "grid", title: "Grid" }, { value: "list", icon: "list", title: "List" }]} />
      </div>

      <Tabs className="wrap" tabs={LIBRARY_TABS.map(t => ({ ...t, count: counts[t.id] }))} value={tab} onChange={setTab} />

      <div style={{ marginTop: 22 }}>
        {isLoading ? (
          <Loading label="Loading your library…" />
        ) : shown.length === 0 ? (
          <EmptyState icon="library" title={q ? "No matches" : emptyCopy.title} body={q ? "Try a different search." : emptyCopy.body}
            primaryAction={!q && tab === "all" ? <Button variant="primary" icon="sparkles" onClick={() => setAdding(true)}>Add a novel</Button> : null}
            secondaryAction={!q && tab === "all" ? <Button variant="ghost" icon="compass" onClick={() => navigate("/discover")}>Browse shared library</Button> : null} />
        ) : view === "grid" ? (
          <div className="lib-grid">
            {shown.map(n => <GridCard key={n.id} n={n} onMove={moveShelf} onRemove={removeFromLibrary} />)}
          </div>
        ) : (
          <div className="card lib-list" style={{ padding: 6 }}>
            {shown.map(n => <ListRow key={n.id} n={n} onMove={moveShelf} onRemove={removeFromLibrary} />)}
          </div>
        )}
      </div>

      {adding && (
        <AddNovelDialog onClose={() => setAdding(false)}
                        onCreated={(id) => { setAdding(false); qc.invalidateQueries({ queryKey: ["novels"] }); navigate(`/n/${id}`); }} />
      )}
    </div>
  );
}
