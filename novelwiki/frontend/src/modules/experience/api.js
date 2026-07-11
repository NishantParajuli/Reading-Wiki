import { API_BASE, getJSON, postJSON } from "../../shared/api/http.js";
const novel = (id) => `${API_BASE}/novels/${id}`;
export const experienceApi = {
  home: () => getJSON(`${API_BASE}/home`),
  activity(status, limit) {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (limit) params.set("limit", limit);
    const query = params.toString();
    return getJSON(`${API_BASE}/activity${query ? `?${query}` : ""}`);
  },
  recap: (id, ceiling) => postJSON(`${novel(id)}/recap`, ceiling != null ? { ceiling } : {}),
  novelHealth: (id, voiceId) => getJSON(`${novel(id)}/health${voiceId ? `?voice_id=${encodeURIComponent(voiceId)}` : ""}`),
};
