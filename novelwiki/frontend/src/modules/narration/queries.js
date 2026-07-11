import { useQuery } from "@tanstack/react-query";
import { narrationApi } from "./api.js";

export function useVoicesQuery() {
  return useQuery({
    queryKey: ["tts-voices"],
    queryFn: () => narrationApi.ttsVoices(),
    staleTime: 5 * 60_000,
  });
}

export function useAudioCoverageQuery(novelId) {
  return useQuery({
    queryKey: ["audio-coverage", Number(novelId)],
    queryFn: () => narrationApi.audioCoverage(novelId),
    enabled: novelId != null,
    staleTime: 30_000,
  });
}
