/* ============================================================
   NovelLayout — the per-novel context for /n/:novelId/*.
   Holds novel detail (shared query), the codex ceiling (defaults to the
   reader's trusted progress and is clamped server-side), and codex stats.
   ============================================================ */
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { Outlet, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { API } from "../lib/api.js";
import { useNovelQuery } from "../lib/queries.js";
import { useDebounce } from "../lib/hooks.js";
import { Loading, EmptyState } from "../components/ui.jsx";

const NovelContext = createContext(null);
export const useNovel = () => useContext(NovelContext);

export function NovelLayout() {
  const { novelId: novelIdParam } = useParams();
  const novelId = Number(novelIdParam);
  const qc = useQueryClient();
  const { data: novel, isLoading, isError, refetch } = useNovelQuery(novelId);

  const [ceiling, setCeiling] = useState(1);
  const [ceilingInit, setCeilingInit] = useState(false);
  const [stats, setStats] = useState(null);
  const debCeiling = useDebounce(ceiling, 250);

  // Default the ceiling to trusted read progress once the novel loads.
  useEffect(() => {
    if (!novel || ceilingInit) return;
    setCeiling((novel.progress && novel.progress.max_chapter_read) || novel.min_chapter || 1);
    setCeilingInit(true);
  }, [novel, ceilingInit]);

  // Reset when navigating to a different novel.
  useEffect(() => { setCeilingInit(false); setStats(null); }, [novelId]);

  // Codex aggregate stats as the ceiling moves; the server clamps requests
  // above trusted progress and we adopt the clamped value.
  useEffect(() => {
    if (!ceilingInit || !novel || !novel.codex_enabled) return;
    let cancel = false;
    API.stats(novelId, debCeiling).then(s => {
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
    return (
      <div className="page">
        <EmptyState icon="x" title="Couldn't open this novel" body="It may be private, deleted, or the link is wrong." />
      </div>
    );
  }

  return (
    <NovelContext.Provider value={value}>
      <Outlet />
    </NovelContext.Provider>
  );
}
