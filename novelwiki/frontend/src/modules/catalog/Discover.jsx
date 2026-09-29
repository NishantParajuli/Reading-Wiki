/* ============================================================
   Discover — the shared library as an editorial front page.

   Search is debounced and mirrored to ?q=; filter pills (?lang ?tr ?tag
   ?fresh ?codex ?audio) and sort (?sort) live in the URL so any view is
   shareable. While browsing (no search or filters, a meaningful order) the
   first stories are set as a cinematic featured strip and the room takes
   the lead book's light; the rest fill the shelf below, paged with
   "Load more". New results FLIP in place of the old ones instead of
   flashing a spinner.

   Adding a book is optimistic: the button turns to "In library", the
   jacket flies home into the shell's Library destination, and a toast
   offers "Open". Failures roll back with an honest message.
   ============================================================ */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { catalogApi } from "./api.js";
import { flyToLibrary } from "./DiscoverFly.js";
import {
  DISCOVER_SORTS, DiscoverCard, FeatureSkeleton, FeaturedStrip, FilterBar, MobileFilters,
} from "./DiscoverParts.jsx";
import { MOTION_CAP, SearchField, ShelfSkeleton, SortMenu, Tally, useSlashFocus } from "./LibraryParts.jsx";
import { experienceApi } from "../experience/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, EmptyState, PageHeader } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { AnimatePresence, LayoutGroup } from "../../motion/index.js";
import { useBookAtmosphere } from "../../atmosphere/store.js";
import { useDebounce, useTitle } from "../../lib/hooks.js";

const PAGE = 60;
const FEATURED = 3;

export function Discover() {
  const [sp, setSp] = useSearchParams();
  const { toast } = useToast();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const searchRef = useRef(null);
  useTitle("Discover");
  useSlashFocus(searchRef);

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
    setSp(prev => {
      const next = new URLSearchParams(prev);
      if (v) next.set(key, v === true ? "1" : v); else next.delete(key);
      return next;
    }, { replace: true });
  };

  // Keep ?q= in the URL in sync with the debounced search text.
  useEffect(() => { setParam("q", debQ.trim()); }, [debQ]); // eslint-disable-line react-hooks/exhaustive-deps

  const [items, setItems] = useState(null);
  const [total, setTotal] = useState(0);
  // What the shelf on screen answers (kept until the next answer lands).
  const [shown, setShown] = useState({ browse: false, query: "", filtered: false, sortLabel: "" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [appendFrom, setAppendFrom] = useState(0);
  const [addedIds, setAddedIds] = useState(() => new Set());

  const filterKey = useMemo(() => JSON.stringify({ debQ, ...filters }), [debQ, sp]); // eslint-disable-line react-hooks/exhaustive-deps
  const pending = useRef(new Set());

  const activeCount = [filters.language, filters.translation, filters.tag, filters.freshness].filter(Boolean).length
    + (filters.has_codex ? 1 : 0) + (filters.has_audio ? 1 : 0);
  const query = debQ.trim();
  const sortLabel = (DISCOVER_SORTS.find(s => s.id === filters.sort) || DISCOVER_SORTS[0]).label;
  // Browsing (not searching or filtering) under a meaningful order gets the front page.
  const browsing = !query && !activeCount && filters.sort !== "title";

  /* New query: keep the current shelf on screen (dimmed) until the answer
     lands, then let the books FLIP into their new places. */
  useEffect(() => {
    let cancel = false;
    setLoading(true);
    setError(null);
    experienceApi.discover({ q: debQ.trim(), ...filters, offset: 0, limit: PAGE }).then(r => {
      if (cancel) return;
      const list = Array.isArray(r) ? r : (r.items || []);
      setItems(list);
      setTotal(Array.isArray(r) ? list.length : (r.total ?? list.length));
      setShown({ browse: browsing, query, filtered: activeCount > 0, sortLabel });
      setAppendFrom(0);
      setLoading(false);
    }).catch(e => {
      if (cancel) return;
      setItems(null);
      setTotal(0);
      setError(e || new Error("Unavailable"));
      setLoading(false);
    });
    return () => { cancel = true; };
  }, [filterKey, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadMore() {
    setLoadingMore(true);
    try {
      const r = await experienceApi.discover({ q: debQ.trim(), ...filters, offset: items.length, limit: PAGE });
      const list = Array.isArray(r) ? r : (r.items || []);
      setAppendFrom(items.length);
      setItems(prev => [...prev, ...list]);
      if (!Array.isArray(r) && r.total != null) setTotal(r.total);
    } catch (e) {
      toast(e.message || "Couldn't load more.", { tone: "danger" });
    } finally {
      setLoadingMore(false);
    }
  }

  /* Optimistic add: flips to "In library" instantly, the jacket flies home,
     rolls back on failure. The request always starts first. */
  async function add(n, coverEl) {
    if (addedIds.has(n.id) || pending.current.has(n.id)) return;
    pending.current.add(n.id);
    setAddedIds(prev => new Set(prev).add(n.id));
    const request = catalogApi.addToLibrary(n.id);
    flyToLibrary(coverEl);
    try {
      await request;
      qc.invalidateQueries({ queryKey: ["novels"] });
      toast(`Added “${n.title}” to your library.`, {
        tone: "ok",
        action: { label: "Open", onClick: () => navigate(`/n/${n.id}`) },
      });
    } catch (e) {
      setAddedIds(prev => { const s = new Set(prev); s.delete(n.id); return s; });
      toast(e.message || "Couldn't add it.", { tone: "danger" });
    } finally {
      pending.current.delete(n.id);
    }
  }

  const clearAll = () => {
    setSp(prev => {
      const next = new URLSearchParams();
      const sort = prev.get("sort");
      if (sort) next.set("sort", sort);
      if (prev.get("q")) next.set("q", prev.get("q"));
      return next;
    }, { replace: true });
  };
  const clearEverything = () => { setQ(""); setSp(new URLSearchParams(), { replace: true }); };

  const featured = shown.browse && items ? items.slice(0, FEATURED) : [];
  const shelf = items ? items.slice(featured.length) : [];
  useBookAtmosphere(featured[0] || null);
  const layoutKey = useMemo(() => shelf.map(n => n.id).join(","), [shelf]);

  const firstLoad = loading && items == null && !error;
  const refreshing = loading && items != null;
  const status = error ? "The shared library is unavailable"
    : firstLoad ? "Loading the shared library…"
    : refreshing ? "Updating results…"
    : `${total.toLocaleString()} ${total === 1 ? "story" : "stories"}${query ? ` matching “${query}”` : activeCount ? " match these filters" : " in the shared library"}`;

  let body;
  if (firstLoad) {
    body = (
      <>
        {browsing && <FeatureSkeleton />}
        <ShelfSkeleton view="grid" count={browsing ? 5 : 10} />
      </>
    );
  } else if (error) {
    body = (
      <EmptyState icon="alert" title="The shared library couldn't load" body="Check your connection, then try again."
        primaryAction={<Button icon="refresh" loading={loading} onClick={() => setAttempt(a => a + 1)}>Try again</Button>} />
    );
  } else if (!items.length) {
    body = query || activeCount
      ? (
        <EmptyState icon="compass" title="Nothing matches — yet"
          body={query ? `No shared stories match “${query}”${activeCount ? " with these filters" : ""}. Try another title or loosen a filter.` : "No shared stories match these filters. Try loosening one."}
          primaryAction={<Button variant="ghost" icon="x" onClick={clearEverything}>Clear search & filters</Button>} />
      )
      : (
        <EmptyState icon="compass" title="Nothing to discover" body="Global novels and other readers' public uploads show up here."
          primaryAction={<Button variant="ghost" icon="library" onClick={() => navigate("/library")}>Back to your library</Button>} />
      );
  } else {
    body = (
      <>
        {featured.length > 0 && (
          <FeaturedStrip key={featured.map(n => n.id).join("-")} items={featured} label={shown.sortLabel}
                         addedIds={addedIds} onAdd={add} />
        )}
        {shelf.length > 0 && (
          <section className="disc-shelf" aria-labelledby="disc-shelf-title">
            <div className="disc-section-head">
              <h2 className="section-title" id="disc-shelf-title">
                {shown.browse ? "More to explore"
                  : shown.query ? <>Results for <em>“{shown.query}”</em></>
                  : shown.filtered ? "Filtered stories"
                  : <>The shared shelf, <em>A–Z</em></>}
              </h2>
              <span className="disc-section-count"><Tally value={total} /> {shown.query || shown.filtered ? (total === 1 ? "match" : "matches") : "in the shared library"}</span>
            </div>
            <LayoutGroup id="discover-shelf">
              <ul className="lib-grid disc-grid">
                <AnimatePresence mode="popLayout" initial>
                  {shelf.map((n, i) => {
                    const fresh = Math.max(0, i + featured.length - appendFrom);
                    return (
                      <DiscoverCard key={n.id} n={n} added={addedIds.has(n.id)} onAdd={add}
                                    animated={i < MOTION_CAP} rise={Math.min(fresh, 12)}
                                    delay={(featured.length ? 0.45 : 0.1) + Math.min(fresh, 14) * 0.05}
                                    layoutDependency={layoutKey} />
                    );
                  })}
                </AnimatePresence>
              </ul>
            </LayoutGroup>
          </section>
        )}
        {items.length < total ? (
          <div className="disc-more">
            <div className="disc-more-meter" aria-hidden="true"><span style={{ width: `${Math.min(100, Math.round((items.length / total) * 100))}%` }} /></div>
            <p className="disc-more-note">Showing <b>{items.length.toLocaleString()}</b> of <b>{total.toLocaleString()}</b></p>
            <Button variant="ghost" icon="chevronDown" loading={loadingMore} onClick={loadMore}>Load more</Button>
          </div>
        ) : items.length > FEATURED * 2 && (
          <p className="disc-end"><Icon name="wave" size={18} />That's the whole shared shelf — {total.toLocaleString()} {total === 1 ? "story" : "stories"}.</p>
        )}
      </>
    );
  }

  return (
    <div className="page page-enter disc-page">
      <PageHeader
        eyebrow={<><span className="disc-eyebrow-mark" aria-hidden="true" />The shared library</>}
        title="Discover"
        subtitle="Global novels and other readers' public shelves. Add any of them and read with your own progress." />

      <div className="disc-controls rise" style={{ "--i": 4 }}>
        <div className="disc-searchrow">
          <SearchField ref={searchRef} className="disc-search" value={q} onChange={setQ}
                       placeholder="Search shared titles…" label="Search the shared library" shortcut />
          <SortMenu value={filters.sort} options={DISCOVER_SORTS} className="disc-sort"
                    onChange={v => setParam("sort", v === "recent" ? "" : v)} />
        </div>
        <FilterBar filters={filters} setParam={setParam} activeCount={activeCount} onClearAll={clearAll} />
        <MobileFilters filters={filters} setParam={setParam} activeCount={activeCount} onClearAll={clearAll}
                       total={total} loading={loading} />
      </div>

      {/* While browsing, the shelf heading carries the count; the status stays for screen readers. */}
      <p className={"lib-status disc-status" + (shown.browse && !loading && !error && items && items.length ? " sr-only" : "")} role="status">
        <span className={"lib-status-dot" + (loading ? " is-busy" : "")} aria-hidden="true" />{status}
      </p>

      <div className={"disc-stage" + (refreshing ? " is-refreshing" : "")} aria-busy={loading || undefined}>
        {refreshing && <span className="disc-refresh-line" aria-hidden="true" />}
        {body}
      </div>
    </div>
  );
}
