import { useQuery } from "@tanstack/react-query";
import { readingApi } from "./api.js";

export function useChaptersQuery(novelId) {
  return useQuery({
    queryKey: ["chapters", Number(novelId)],
    queryFn: () => readingApi.chapters(novelId),
    enabled: novelId != null,
    staleTime: 60_000,
  });
}
