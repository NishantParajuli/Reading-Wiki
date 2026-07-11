import { useQuery } from "@tanstack/react-query";
import { experienceApi } from "./api.js";

const ATTENTION = new Set(["awaiting_review", "awaiting_ocr_confirm", "ocr_paused"]);

export function isActiveJob(job) {
  return !!job.cancelable || ATTENTION.has(job.status);
}

export function useHomeQuery() {
  return useQuery({ queryKey: ["home"], queryFn: () => experienceApi.home(), staleTime: 15_000 });
}

export function useActivityQuery() {
  return useQuery({
    queryKey: ["activity"],
    queryFn: async () => {
      const response = await experienceApi.activity("all", 100);
      return response.jobs || [];
    },
    refetchInterval: (query) => {
      const jobs = query.state.data || [];
      return jobs.some(isActiveJob) ? 3500 : 30_000;
    },
    staleTime: 2000,
  });
}
