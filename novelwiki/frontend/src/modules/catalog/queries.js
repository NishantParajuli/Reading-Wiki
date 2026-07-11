import { useQuery } from "@tanstack/react-query";
import { catalogApi } from "./api.js";

export function useNovelQuery(novelId, opts = {}) {
  return useQuery({
    queryKey: ["novel", Number(novelId)],
    queryFn: () => catalogApi.novel(novelId),
    enabled: novelId != null,
    ...opts,
  });
}

export function useNovelsQuery() {
  return useQuery({ queryKey: ["novels"], queryFn: () => catalogApi.novels() });
}
