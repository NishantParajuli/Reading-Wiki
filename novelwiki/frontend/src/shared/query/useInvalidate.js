import { useQueryClient } from "@tanstack/react-query";

export function useInvalidate() {
  const queryClient = useQueryClient();
  return (...keys) => keys.forEach(
    (key) => queryClient.invalidateQueries({ queryKey: key }),
  );
}
