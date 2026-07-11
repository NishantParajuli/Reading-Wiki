/* Compatibility facade for feature-owned TanStack Query hooks. */
import { useQueryClient } from "@tanstack/react-query";

export { useNovelQuery, useNovelsQuery } from "../modules/catalog/queries.js";
export { useChaptersQuery } from "../modules/reading/queries.js";
export { useVoicesQuery, useAudioCoverageQuery } from "../modules/narration/queries.js";
export { isActiveJob, useActivityQuery, useHomeQuery } from "../modules/experience/queries.js";

export function useInvalidate() {
  const queryClient = useQueryClient();
  return (...keys) => keys.forEach(
    (key) => queryClient.invalidateQueries({ queryKey: key }),
  );
}
