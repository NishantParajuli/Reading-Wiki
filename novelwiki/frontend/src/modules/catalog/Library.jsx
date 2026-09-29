/* ============================================================
   Library — the reader's private collection: a luminous shelf at night.

   Covers are the heroes. A glass toolbar docks under the island with the
   shelf tabs (sliding lozenge + live counts), search ("/" to focus), sort
   and the grid/list toggle — all persisted (nw-lib-tab/-view/-sort).
   The header's quiet summary is computed from real data only.

   Motion: the shelf rises in a capped cascade; changing shelf, search or
   sort FLIPs the books into place while leavers sink into the tide; the
   grid/list toggle flies every jacket to its new home. Lingering on a book
   (fine pointers) tints the room with its cover. Shelf moves and removals
   are optimistic with rollback and an Undo toast.
   ============================================================ */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { catalogApi } from "./api.js";
import { AddNovelDialog } from "./AddNovelDialog.jsx";
import { useNovelsQuery } from "./queries.js";
import {
  MOTION_CAP, SearchField, ShelfCard, ShelfRow, ShelfSkeleton, SortMenu, Tally, readPct, useSlashFocus,
} from "./LibraryParts.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, EmptyState, PageHeader, SegmentedControl, Tabs } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { AnimatePresence, LayoutGroup } from "../../motion/index.js";
import { prefersReducedMotion, useReadySignal } from "../../motion/navigation.js";
import { useBookAtmosphere } from "../../atmosphere/store.js";
import { useLocalStorage, useTitle } from "../../lib/hooks.js";
import { SHELF_LABELS } from "../../lib/constants.js";

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
  all: { icon: "library", title: "No novels yet", body: "Add your first novel to start reading." },
  reading: { icon: "bookOpen", title: "Nothing on the go", body: "Open a book and it lands here." },
  to_read: { icon: "bookmark", title: "The pile is empty", body: "Shelve something for later from a novel's page." },
  completed: { icon: "circleCheck", title: "Nothing finished yet", body: "The ending will come." },
};

const COMPARE = {
  recent_read: (a, b) => String(b.last_read_at || "").localeCompare(String(a.last_read_at || "")),
  recent_updated: (a, b) => String(b.source_updated_at || "").localeCompare(String(a.source_updated_at || "")),
  title: (a, b) => String(a.title || "").localeCompare(String(b.title || "")),
  progress: (a, b) => readPct(b) - readPct(a),
};

/* Linger on a book (fine pointer, motion allowed) and the room takes its colour. */
function useLingerAtmosphere() {
  const [book, setBook] = useState(null);
  const timer = useRef(0);
  const enabled = useMemo(() => {
    try { return window.matchMedia("(hover: hover) and (pointer: fine)").matches && !prefersReducedMotion(); }
    catch { return false; }
  }, []);
  useBookAtmosphere(book);
  useEffect(() => () => clearTimeout(timer.current), []);
  const onFocusBook = useCallback((n) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setBook(n ? { id: n.id, title: n.title, cover_url: n.cover_url } : null), n ? 850 : 1400);
  }, []);
  return enabled ? onFocusBook : null;
}

function FirstShelf({ onAdd, onImport }) {
  const ways = [
    { icon: "globe", title: "From the web", body: "Paste a novel's page and Tideglass keeps it in step as chapters arrive.", action: onAdd, label: "Add a novel" },
    { icon: "upload", title: "From a file", body: "Bring an EPUB or PDF — scanned pages included.", action: onImport, label: "Import a book" },
    { icon: "compass", title: "From the shared library", body: "Pick up something other readers have shelved.", to: "/discover", label: "Browse shared library" },
  ];
  return (
    <section className="lib-first rise" aria-labelledby="lib-first-title">
      <div className="lib-first-glow" aria-hidden="true" />
      <p className="section-eyebrow">An empty shelf</p>
      <h2 className="lib-first-title" id="lib-first-title">No novels yet</h2>
      <p className="lib-first-body">Add your first novel to start reading. Three ways to begin:</p>
      <div className="lib-first-ways">
        {ways.map((w, i) => {
          const inner = (
            <>
              <span className="lib-first-icon"><Icon name={w.icon} size={20} /></span>
              <span className="lib-first-copy"><b>{w.title}</b><span>{w.body}</span></span>
              <span className="lib-first-go">{w.label} <Icon name="arrowRight" size={14} /></span>
            </>
          );
          return w.to
            ? <Link key={w.title} className="lib-first-way rise" style={{ "--i": i + 2 }} to={w.to}>{inner}</Link>
            : <button key={w.title} type="button" className="lib-first-way rise" style={{ "--i": i + 2 }} onClick={w.action}>{inner}</button>;
        })}
      </div>
    </section>
  );
}

export function Library() {
  const { data: novels, isLoading, isError, isFetching, refetch } = useNovelsQuery();
  const qc = useQueryClient();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [storedTab, setTab] = useLocalStorage("nw-lib-tab", "all");
  const [storedView, setView] = useLocalStorage("nw-lib-view", "grid");
  const [storedSort, setSort] = useLocalStorage("nw-lib-sort", "recent_read");
  const tab = LIBRARY_TABS.some(t => t.id === storedTab) ? storedTab : "all";
  const view = storedView === "list" ? "list" : "grid";
  const sort = COMPARE[storedSort] ? storedSort : "recent_read";
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const searchRef = useRef(null);
  const onFocusBook = useLingerAtmosphere();
  useTitle("Library");
  useReadySignal("library", !isLoading);
  useSlashFocus(searchRef);

  // A view toggle morphs jackets between grid and list instead of re-cascading.
  const lastView = useRef(view);
  const morph = lastView.current !== view;
  useEffect(() => { lastView.current = view; }, [view]);

  const all = useMemo(() => novels || [], [novels]);
  const counts = useMemo(() => {
    const c = { all: all.length, reading: 0, to_read: 0, completed: 0 };
    all.forEach(n => { if (n.shelf && c[n.shelf] != null) c[n.shelf] += 1; });
    return c;
  }, [all]);
  const chaptersRead = useMemo(() => Math.floor(all.reduce((sum, n) => sum + (Number(n.max_chapter_read) || 0), 0)), [all]);

  const needle = q.trim().toLowerCase();
  const shown = useMemo(() => {
    let list = tab === "all" ? all : all.filter(n => n.shelf === tab);
    if (needle) {
      list = list.filter(n => String(n.title || "").toLowerCase().includes(needle) || String(n.author || "").toLowerCase().includes(needle));
    }
    return [...list].sort(COMPARE[sort]);
  }, [all, tab, needle, sort]);
  const layoutKey = useMemo(() => `${view}|${shown.map(n => n.id).join(",")}`, [view, shown]);

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

  const ready = !isLoading && !isError;
  const summary = isLoading
    ? <span className="lib-summary is-quiet">Gathering your shelves…</span>
    : ready && (all.length
      ? (
        <span className="lib-summary">
          <span className="lib-summary-part"><b><Tally value={all.length} /></b> {all.length === 1 ? "book" : "books"} on your shelves</span>
          {chaptersRead > 0 && (
            <>
              <span className="lib-summary-sep" aria-hidden="true">·</span>
              <span className="lib-summary-part"><b><Tally value={chaptersRead} /></b> {chaptersRead === 1 ? "chapter" : "chapters"} read</span>
            </>
          )}
        </span>
      )
      : <span className="lib-summary is-quiet">Your shelves are waiting for their first book.</span>);

  const shelfName = LIBRARY_TABS.find(t => t.id === tab).label;
  const status = isLoading ? "Finding your books…"
    : isError ? "Library unavailable"
    : needle ? `${shown.length} ${shown.length === 1 ? "book" : "books"} matching “${q.trim()}”`
    : tab === "all" ? `${shown.length} ${shown.length === 1 ? "book" : "books"} in your collection`
    : `${shown.length} ${shown.length === 1 ? "book" : "books"} on ${shelfName}`;

  const emptyCopy = EMPTY_COPY[tab] || EMPTY_COPY.all;
  const itemProps = { q, morph, layoutDependency: layoutKey, onMove: moveShelf, onRemove: removeFromLibrary };

  let body;
  if (isLoading) {
    body = <ShelfSkeleton view={view} />;
  } else if (isError) {
    body = (
      <EmptyState icon="alert" title="Your library couldn't load" body="Try again to see your books and saved progress."
        primaryAction={<Button icon="refresh" loading={isFetching} onClick={() => refetch()}>Try again</Button>} />
    );
  } else if (!all.length) {
    body = <FirstShelf onAdd={() => setAdding(true)} onImport={() => navigate("/import")} />;
  } else {
    body = (
      <LayoutGroup id="library-shelf">
        {view === "grid" ? (
          <ul className="lib-grid" aria-label={`${shelfName} books`}>
            <AnimatePresence mode="popLayout" initial>
              {shown.map((n, i) => (
                <ShelfCard key={n.id} n={n} index={i} animated={i < MOTION_CAP} onFocusBook={onFocusBook} {...itemProps} />
              ))}
            </AnimatePresence>
          </ul>
        ) : (
          <div className="lib-list-wrap">
            <div className="lib-list-head" aria-hidden="true">
              <span /><span>Title</span><span>Progress</span><span>Shelf</span><span>Last read</span><span />
            </div>
            <ul className="lib-list" aria-label={`${shelfName} books`}>
              <AnimatePresence mode="popLayout" initial>
                {shown.map((n, i) => (
                  <ShelfRow key={n.id} n={n} index={i} animated={i < MOTION_CAP} {...itemProps} />
                ))}
              </AnimatePresence>
            </ul>
          </div>
        )}
        {shown.length === 0 && (
          needle
            ? <EmptyState key={`q-${tab}`} icon="search" title="No matches" body={`Nothing on this shelf matches “${q.trim()}”. Try a different search.`}
                primaryAction={<Button variant="ghost" icon="x" onClick={() => setQ("")}>Clear search</Button>} />
            : <EmptyState key={`t-${tab}`} icon={emptyCopy.icon} title={emptyCopy.title} body={emptyCopy.body}
                primaryAction={<Button variant="ghost" icon="library" onClick={() => setTab("all")}>Show all books</Button>}
                secondaryAction={tab === "to_read" ? <Button variant="ghost" icon="compass" onClick={() => navigate("/discover")}>Browse shared library</Button> : null} />
        )}
      </LayoutGroup>
    );
  }

  return (
    <div className="page page-enter lib-page">
      <PageHeader
        eyebrow={<><span className="lib-eyebrow-mark" aria-hidden="true" />Your collection</>}
        title="Library"
        subtitle={summary}
        actions={
          <>
            <Button variant="ghost" icon="upload" onClick={() => navigate("/import")}>Import</Button>
            <Button variant="primary" icon="plus" onClick={() => setAdding(true)}>Add novel</Button>
          </>
        } />

      <section className="lib-controls rise" style={{ "--i": 5 }} aria-label="Library tools">
        <Tabs className="lib-shelves" tabs={LIBRARY_TABS.map(t => ({ ...t, count: novels ? counts[t.id] : undefined }))}
              value={tab} onChange={setTab} />
        <div className="lib-tools">
          <SearchField ref={searchRef} className="lib-search" value={q} onChange={setQ}
                       placeholder="Search your library…" label="Search your library" shortcut />
          <SortMenu value={sort} options={SORTS} onChange={setSort} className="lib-sort" />
          <SegmentedControl fit ariaLabel="View" value={view} onChange={setView} className="lib-view"
            options={[{ value: "grid", icon: "grid", title: "Grid" }, { value: "list", icon: "list", title: "List" }]} />
        </div>
      </section>

      <p className="lib-status" role="status"><span className="lib-status-dot" aria-hidden="true" />{status}</p>

      <div className="lib-stage" aria-busy={isLoading || undefined}>{body}</div>

      {adding && (
        <AddNovelDialog onClose={() => setAdding(false)}
                        onCreated={(id) => { setAdding(false); qc.invalidateQueries({ queryKey: ["novels"] }); navigate(`/n/${id}`); }} />
      )}
    </div>
  );
}
