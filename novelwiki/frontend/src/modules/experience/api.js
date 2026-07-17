import { API_BASE, getJSON, postJSONStream } from "../../shared/api/http.js";
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
  recap: (id, ceiling) => postJSONStream(`${novel(id)}/recap`, ceiling != null ? { ceiling } : {}),
  novelHealth: (id, voiceId) => getJSON(`${novel(id)}/health${voiceId ? `?voice_id=${encodeURIComponent(voiceId)}` : ""}`),
  discover(opts) {
    const input = (typeof opts === "string" || opts == null) ? { q: opts } : opts;
    const params = new URLSearchParams();
    if (input.q) params.set("q", input.q);
    if (input.language) params.set("language", input.language);
    if (input.tag) params.set("tag", input.tag);
    if (input.translation) params.set("translation", input.translation);
    if (input.has_codex) params.set("has_codex", "true");
    if (input.has_audio) params.set("has_audio", "true");
    if (input.freshness) params.set("freshness", input.freshness);
    if (input.sort) params.set("sort", input.sort);
    if (input.offset) params.set("offset", input.offset);
    if (input.limit) params.set("limit", input.limit);
    const query = params.toString();
    return getJSON(`${API_BASE}/discover${query ? `?${query}` : ""}`);
  },
  costEstimate(id, action, input = {}) {
    const params = new URLSearchParams({ action });
    if (input.from_chapter != null) params.set("from_chapter", input.from_chapter);
    if (input.to_chapter != null) params.set("to_chapter", input.to_chapter);
    if (input.force) params.set("force", "true");
    if (input.voice_id) params.set("voice_id", input.voice_id);
    return getJSON(`${novel(id)}/cost-estimate?${params}`);
  },
};
