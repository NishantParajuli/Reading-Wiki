import { API_BASE, getJSON, postJSON } from "../../shared/api/http.js";

export const workApi = {
  jobs(opts = {}) {
    const params = new URLSearchParams();
    for (const key of ["kind", "status", "novel_id", "user_id", "limit"]) {
      if (opts[key] != null && opts[key] !== "") params.set(key, opts[key]);
    }
    if (opts.active) params.set("active", "1");
    const query = params.toString();
    return getJSON(`${API_BASE}/jobs${query ? `?${query}` : ""}`);
  },
  job: (id) => getJSON(`${API_BASE}/jobs/${id}`),
  cancelJob: (id) => postJSON(`${API_BASE}/jobs/${id}/cancel`, {}),
};
