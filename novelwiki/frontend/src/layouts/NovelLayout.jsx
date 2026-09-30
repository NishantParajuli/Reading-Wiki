/* ============================================================
   NovelLayout — the per-novel context for /n/:novelId/*.
   Holds novel detail (shared query), the codex ceiling (defaults to the
   reader's trusted progress and is clamped server-side), and codex stats.
   ============================================================ */
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { Link, Outlet, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { codexApi } from "../modules/codex/api.js";
import { useNovelQuery } from "../modules/catalog/queries.js";
import { useDebounce } from "../lib/hooks.js";
import { Button, Loading, EmptyState } from "../components/ui.jsx";
import { useReadySignal } from "../motion/navigation.js";
import { useBookAtmosphere } from "../atmosphere/store.js";

const NovelContext = createContext(null);
export const useNovel = () => useContext(NovelContext);

export function NovelLayout() {
  const { novelId: novelIdParam } = useParams();
  const novelId = Number(novelIdParam);
  const qc = useQueryClient();
  const { data: novel, isLoading, isError, error, refetch } = useNovelQuery(novelId);

  const [ceiling, setCeiling] = useState(1);
  const [ceilingFor, setCeilingFor] = useState(null);
  const [stats, setStats] = useState(null);
  const ceilingInit = ceilingFor === novelId;
  const debCeiling = useDebounce(ceiling, 250);
  // Hold route transitions until the book is on screen; tint the room with it.
  useReadySignal(`novel:${novelId}`, !!novel);
  useBookAtmosphere(novel);

  // Default the ceiling to trusted read progress as soon as this novel is
  // known — adjusted during render, so no tab (or its requests and deep links)
  // ever sees a placeholder ceiling or the previous novel's.
  if (novel && !ceilingInit) {
    setCeiling((novel.progress && novel.progress.max_chapter_read) || novel.min_chapter || 1);
    setCeilingFor(novelId);
    setStats(null);
  }

  // Codex aggregate stats once the ceiling settles; the server clamps requests
  // above trusted progress and we adopt the clamped value. A debounced value
  // still catching up (first load, another novel) is not requested.
  useEffect(() => {
    if (!ceilingInit || !novel || !novel.codex_enabled || debCeiling !== ceiling) return;
    let cancel = false;
    codexApi.stats(novelId, debCeiling).then(s => {
      if (cancel) return;
      setStats(s);
      if (s && s.ceiling_clamped && s.effective_ceiling != null) {
        setCeiling(Number(s.effective_ceiling));
      }
    }).catch(() => { if (!cancel) setStats(null); });
    return () => { cancel = true; };
  }, [novelId, debCeiling, ceilingInit, novel && novel.codex_enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  // Share the current ceiling with the shell (command palette scopes entity search by it).
  useEffect(() => { qc.setQueryData(["ceiling", novelId], ceiling); }, [qc, novelId, ceiling]);

  const value = useMemo(() => {
    if (!novel) return null;
    const minChapter = novel.min_chapter || 1;
    const maxChapter = novel.max_chapter || minChapter;
    const allowedCeiling = Math.min(maxChapter, Math.max(minChapter, (novel.progress && novel.progress.max_chapter_read) || minChapter));
    return {
      novelId,
      novel,
      reloadNovel: refetch,
      ceiling, setCeiling, stats,
      codexMeta: {
        title: novel.title, blurb: novel.description || "",
        min: minChapter, max: allowedCeiling, bookMax: maxChapter,
        totalChapters: maxChapter, count: novel.chapter_count,
      },
    };
  }, [novel, novelId, refetch, ceiling, stats]);

  if (isLoading) return <div className="page"><Loading label="Loading novel…" /></div>;
  if (isError || !novel) {
    // Missing or private is a fact about the book; anything else is a failed
    // request worth retrying.
    const missing = !isError || (error && (error.status === 404 || error.status === 403));
    return (
      <div className="page">
        {missing ? (
          <EmptyState icon="compass" title="This book isn't here"
            body="It may be private, removed, or the link may be wrong."
            primaryAction={<Link className="btn btn-primary" to="/library">Back to your library</Link>}
            secondaryAction={<Link className="btn btn-ghost" to="/discover">Explore Discover</Link>} />
        ) : (
          <EmptyState icon="alert" title="Couldn't open this book"
            body="Something went wrong while loading it. Your library and reading progress are safe."
            primaryAction={<Button icon="refresh" onClick={() => refetch()}>Try again</Button>}
            secondaryAction={<Link className="btn btn-ghost" to="/library">Your library</Link>} />
        )}
      </div>
    );
  }

  return (
    <NovelContext.Provider value={value}>
      <Outlet />
    </NovelContext.Provider>
  );
}
