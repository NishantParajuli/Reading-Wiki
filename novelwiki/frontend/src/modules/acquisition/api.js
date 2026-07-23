import {
  API_BASE, delJSON, getJSON, mutationHeaders, postJSON, postMultipart, putJSON, req,
} from "../../shared/api/http.js";

const novel = (id) => `${API_BASE}/novels/${id}`;
export const acquisitionApi = {
  adapters: () => getJSON(`${API_BASE}/adapters`),
  addSource: (id, body) => postJSON(`${novel(id)}/sources`, body),
  updateSource: (id, sourceId, body) => req("PATCH", `${novel(id)}/sources/${sourceId}`, body),
  scrape: (id, body) => postJSON(`${novel(id)}/scrape`, body),
  uploadImport(file) {
    const form = new FormData(); form.append("file", file);
    return postMultipart(`${API_BASE}/import/upload`, form);
  },
  scanIncoming: () => postJSON(`${API_BASE}/import/scan-incoming`, {}),
  batchImport: (body) => postJSON(`${API_BASE}/import/batch`, body || {}),
  importJobs: () => getJSON(`${API_BASE}/import/jobs`),
  importJob: (id) => getJSON(`${API_BASE}/import/jobs/${id}`),
  updateImportPlan: (id, plan, metadata = null) => putJSON(
    `${API_BASE}/import/jobs/${id}/plan`,
    { plan, metadata },
  ),
  confirmOcr: (id, body) => postJSON(`${API_BASE}/import/jobs/${id}/confirm-ocr`, body || {}),
  commitImport: (id, body) => postJSON(`${API_BASE}/import/jobs/${id}/commit`, body || {}),
  commitSeries: (jobIds, novelId = null) => postJSON(
    `${API_BASE}/import/commit-series`,
    { job_ids: jobIds, novel_id: novelId },
  ),
  cancelImport: (id) => postJSON(`${API_BASE}/import/jobs/${id}/cancel`, {}),
  deleteImport: (id) => delJSON(`${API_BASE}/import/jobs/${id}`),
  CHUNKED_THRESHOLD: 40 * 1024 * 1024,
  CHUNK_SIZE: 8 * 1024 * 1024,
  async uploadChunked(file, onProgress) {
    const init = await postJSON(`${API_BASE}/import/upload/init`, { filename: file.name, size: file.size });
    let offset = 0;
    while (offset < file.size) {
      const end = Math.min(offset + this.CHUNK_SIZE, file.size);
      const response = await fetch(`${API_BASE}/import/upload/${init.id}/chunk`, {
        method: "PUT",
        credentials: "include",
        headers: mutationHeaders({ "Upload-Offset": String(offset), "Content-Type": "application/octet-stream" }),
        body: file.slice(offset, end),
      });
      if (!response.ok) throw new Error(`Chunk upload failed at ${offset}`);
      offset = (await response.json()).offset;
      if (onProgress) onProgress(offset / file.size);
    }
    return postJSON(`${API_BASE}/import/upload/${init.id}/complete`, {});
  },
  async importFile(file, onProgress) {
    if (file.size > this.CHUNKED_THRESHOLD) return this.uploadChunked(file, onProgress);
    const result = await this.uploadImport(file);
    if (onProgress) onProgress(1);
    return result;
  },
};
