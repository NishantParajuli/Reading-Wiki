import { API_BASE, delJSON, getJSON, postJSON, req } from "../../shared/api/http.js";

export const adminApi = {
  users: (q) => getJSON(`${API_BASE}/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  updateUser: (id, body) => req("PATCH", `${API_BASE}/admin/users/${id}`, body),
  deleteUser: (id) => delJSON(`${API_BASE}/admin/users/${id}`),
  usage: () => getJSON(`${API_BASE}/admin/usage`),
  novels(opts = {}) {
    const params = new URLSearchParams();
    if (opts.visibility) params.set("visibility", opts.visibility);
    if (opts.q) params.set("q", opts.q);
    const query = params.toString();
    return getJSON(`${API_BASE}/admin/novels${query ? `?${query}` : ""}`);
  },
  globalNovels: () => getJSON(`${API_BASE}/admin/global-novels`),
  aiPolicy: (id) => getJSON(`${API_BASE}/admin/users/${id}/ai-backend-policy`),
  saveAiPolicy: (id, body) => req("PUT", `${API_BASE}/admin/users/${id}/ai-backend-policy`, body),
  revokeAiPolicy: (id) => delJSON(`${API_BASE}/admin/users/${id}/ai-backend-policy`),
  agyHealth: () => getJSON(`${API_BASE}/admin/ai/agy/health`),
  agySmoke: () => postJSON(`${API_BASE}/admin/ai/agy/smoke-test`, {}),
  retryWaitingAgy: () => postJSON(`${API_BASE}/admin/ai/agy/retry-waiting`, {}),
};
