/* Shared TanStack Query hooks — one definition per server resource so every
   surface reads the same cache (and there is exactly ONE activity poller). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { API } from "./api.js";

export function useNovelQuery(novelId, opts = {}) {
  return useQuery({
    queryKey: ["novel", Number(novelId)],
    queryFn: () => API.novel(novelId),
    enabled: novelId != null,
    ...opts,
  });
}

export function useNovelsQuery() {
  return useQuery({ queryKey: ["novels"], queryFn: () => API.novels() });
}

export function useHomeQuery() {
  return useQuery({ queryKey: ["home"], queryFn: () => API.home(), staleTime: 15_000 });
}

export function useChaptersQuery(novelId) {
  return useQuery({
    queryKey: ["chapters", Number(novelId)],
    queryFn: () => API.chapters(novelId),
    enabled: novelId != null,
    staleTime: 60_000,
  });
}

export function useVoicesQuery() {
  return useQuery({
    queryKey: ["tts-voices"],
    queryFn: () => API.ttsVoices(),
    staleTime: 5 * 60_000,
  });
}

export function useAudioCoverageQuery(novelId) {
  return useQuery({
    queryKey: ["audio-coverage", Number(novelId)],
    queryFn: () => API.audioCoverage(novelId),
    enabled: novelId != null,
    staleTime: 30_000,
  });
}

const ATTENTION = new Set(["awaiting_review", "awaiting_ocr_confirm", "ocr_paused"]);

export function isActiveJob(j) {
  return !!j.cancelable || ATTENTION.has(j.status);
}

/* One poller for all background work: full feed (status=all) at 3.5s while
   anything is active, 30s when idle. Sidebar badge, Home strip, and the Jobs
   page all read this single query. */
export function useActivityQuery() {
  return useQuery({
    queryKey: ["activity"],
    queryFn: async () => {
      const r = await API.activity("all", 100);
      return r.jobs || [];
    },
    refetchInterval: (query) => {
      const jobs = query.state.data || [];
      return jobs.some(isActiveJob) ? 3500 : 30_000;
    },
    staleTime: 2000,
  });
}

export function useInvalidate() {
  const qc = useQueryClient();
  return (...keys) => keys.forEach(k => qc.invalidateQueries({ queryKey: k }));
}
