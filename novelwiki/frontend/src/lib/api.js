/* ============================================================
   api.js — backend client for the multi-novel reading platform (ESM).

   Everything is scoped to a novel id. The reader reads chapter `content`; the
   codex reads are additionally bounded by the server-computed effective ceiling
   for this reader. The browser may request a lower ceiling, but the backend
   clamps it to trusted read progress before any retrieval or synthesis happens.
   ============================================================ */
const API_BASE = "/api";
const CSRF_COOKIE = "tg_csrf";
const CSRF_HEADER = "X-Tideglass-CSRF";
const REQUEST_HEADER = "X-Tideglass-Request";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

// Set by the app root: called when a non-auth request 401s mid-session so the UI can re-gate.
let onUnauthorized = null;
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

function readCookie(name) {
  const parts = (document.cookie || "").split(";").map((p) => p.trim());
  const prefix = `${name}=`;
  for (const part of parts) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return "";
}

function mutationHeaders(headers) {
  const h = headers || {};
  h[REQUEST_HEADER] = "1";
  const csrf = readCookie(CSRF_COOKIE);
  if (csrf) h[CSRF_HEADER] = csrf;
  return h;
}

async function req(method, url, body) {
  const opts = { method, credentials: "include", headers: { Accept: "application/json" } };
  if (!SAFE_METHODS.has(method.toUpperCase())) mutationHeaders(opts.headers);
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body || {});
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    if (res.status === 401 && url.indexOf("/auth/") === -1 && onUnauthorized) {
      try { onUnauthorized(); } catch (e) { /* re-gate is best-effort */ }
    }
    let detail = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) { /* non-JSON error body */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}
const getJSON = (url) => req("GET", url);
const postJSON = (url, body) => req("POST", url, body || {});
const putJSON = (url, body) => req("PUT", url, body);
const delJSON = (url) => req("DELETE", url);

async function postMultipart(url, fd) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: mutationHeaders(),
    body: fd,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) { /* ignore */ }
    const err = new Error(detail); err.status = res.status; throw err;
  }
  return res.json();
}

const TYPE_PORTRAIT = {
  character: "PORTRAIT", location: "PLACE", faction: "EMBLEM",
  item: "OBJECT", concept: "CONCEPT", organization: "EMBLEM",
};
export function portraitLabel(type, name) {
  const p = TYPE_PORTRAIT[type] || "ENTRY";
  return name ? `${p} — ${name}` : p;
}
export function mapEntity(e) {
  return {
    id: e.id,
    name: e.canonical_name,
    type: e.type,
    firstSeen: e.first_seen_chapter,
    blurb: e.description || "",
    portrait: portraitLabel(e.type, e.canonical_name),
  };
}

export function buildCiteMap(citations) {
  const map = {};
  (citations || []).forEach((c) => {
    const kind = (c.kind || "").toLowerCase();
    map[`${kind}:${c.id}`] = {
      ch: c.chapter,
      quote: c.snippet || "",
      chunk: `${kind} ${c.id}`,
      label: `${kind.charAt(0).toUpperCase()}${kind.slice(1)} ${c.id}`,
      kind,
      id: c.id,
    };
  });
  return map;
}

const N = (id) => `${API_BASE}/novels/${id}`;

export const API = {
  base: API_BASE,

  // ── Auth / account ──
  auth: {
    me() { return getJSON(`${API_BASE}/auth/me`); },
    login(identifier, password) { return postJSON(`${API_BASE}/auth/login`, { identifier, password }); },
    register(email, username, password) { return postJSON(`${API_BASE}/auth/register`, { email, username, password }); },
    logout() { return postJSON(`${API_BASE}/auth/logout`, {}); },
    requestReset(email) { return postJSON(`${API_BASE}/auth/request-reset`, { email }); },
    reset(token, password) { return postJSON(`${API_BASE}/auth/reset`, { token, password }); },
    verify(token) { return postJSON(`${API_BASE}/auth/verify`, { token }); },
    providers() { return getJSON(`${API_BASE}/auth/providers`); },
    oauthStart(provider) { window.location.href = `${API_BASE}/auth/oauth/${provider}/start`; },
    links() { return getJSON(`${API_BASE}/auth/links`); },
    changePassword(currentPassword, newPassword) {
      return postJSON(`${API_BASE}/auth/change-password`, { current_password: currentPassword || null, new_password: newPassword });
    },
  },

  // ── Profiles / account ──
  profile(username) { return getJSON(`${API_BASE}/users/${encodeURIComponent(username)}`); },
  updateMe(body) { return req("PATCH", `${API_BASE}/me`, body); },
  uploadAvatar(file) {
    const fd = new FormData();
    fd.append("file", file);
    return postMultipart(`${API_BASE}/me/avatar`, fd);
  },

  // ── Admin dashboard ──
  admin: {
    users(q) { return getJSON(`${API_BASE}/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`); },
    updateUser(id, body) { return req("PATCH", `${API_BASE}/admin/users/${id}`, body); },
    deleteUser(id) { return delJSON(`${API_BASE}/admin/users/${id}`); },
    usage() { return getJSON(`${API_BASE}/admin/usage`); },
    novels(opts = {}) {
      const p = new URLSearchParams();
      if (opts.visibility) p.set("visibility", opts.visibility);
      if (opts.q) p.set("q", opts.q);
      const qs = p.toString();
      return getJSON(`${API_BASE}/admin/novels${qs ? `?${qs}` : ""}`);
    },
    globalNovels() { return getJSON(`${API_BASE}/admin/global-novels`); },
    aiPolicy(id) { return getJSON(`${API_BASE}/admin/users/${id}/ai-backend-policy`); },
    saveAiPolicy(id, body) { return req("PUT", `${API_BASE}/admin/users/${id}/ai-backend-policy`, body); },
    revokeAiPolicy(id) { return delJSON(`${API_BASE}/admin/users/${id}/ai-backend-policy`); },
    agyHealth() { return getJSON(`${API_BASE}/admin/ai/agy/health`); },
    agySmoke() { return postJSON(`${API_BASE}/admin/ai/agy/smoke-test`, {}); },
    retryWaitingAgy() { return postJSON(`${API_BASE}/admin/ai/agy/retry-waiting`, {}); },
  },

  // ── Library / novels ──
  adapters() { return getJSON(`${API_BASE}/adapters`); },
  novels() { return getJSON(`${API_BASE}/novels`); },
  createNovel(body) { return postJSON(`${API_BASE}/novels`, body); },
  novel(id) { return getJSON(N(id)); },
  updateNovel(id, body) { return req("PATCH", N(id), body); },
  uploadNovelCover(id, file) {
    const fd = new FormData();
    fd.append("file", file);
    return postMultipart(`${N(id)}/cover`, fd);
  },
  deleteNovel(id) { return delJSON(N(id)); },
  // Discover accepts a filter object {q, language, tag, translation, has_codex, has_audio,
  // freshness, sort, offset, limit}. Returns {items, total, offset, limit}.
  discover(opts) {
    const o = (typeof opts === "string" || opts == null) ? { q: opts } : opts;
    const p = new URLSearchParams();
    if (o.q) p.set("q", o.q);
    if (o.language) p.set("language", o.language);
    if (o.tag) p.set("tag", o.tag);
    if (o.translation) p.set("translation", o.translation);
    if (o.has_codex) p.set("has_codex", "true");
    if (o.has_audio) p.set("has_audio", "true");
    if (o.freshness) p.set("freshness", o.freshness);
    if (o.sort) p.set("sort", o.sort);
    if (o.offset) p.set("offset", o.offset);
    if (o.limit) p.set("limit", o.limit);
    const qs = p.toString();
    return getJSON(`${API_BASE}/discover${qs ? `?${qs}` : ""}`);
  },
  addToLibrary(id) { return postJSON(`${N(id)}/library`, {}); },
  removeFromLibrary(id) { return delJSON(`${N(id)}/library`); },
  setVisibility(id, visibility) { return req("PATCH", `${N(id)}/visibility`, { visibility }); },
  usage() { return getJSON(`${API_BASE}/me/usage`); },
  addSource(id, body) { return postJSON(`${N(id)}/sources`, body); },
  updateSource(id, sid, body) { return req("PATCH", `${N(id)}/sources/${sid}`, body); },
  scrape(id, body) { return postJSON(`${N(id)}/scrape`, body); },

  // ── Reader ──
  chapters(id) { return getJSON(`${N(id)}/chapters`); },
  chapter(id, number) { return getJSON(`${N(id)}/chapter/${number}`); },
  getProgress(id) { return getJSON(`${N(id)}/progress`); },
  setProgress(id, body) { return putJSON(`${N(id)}/progress`, body); },
  bookmarks(id) { return getJSON(`${N(id)}/bookmarks`); },
  addBookmark(id, body) { return postJSON(`${N(id)}/bookmarks`, body); },
  delBookmark(id, bid) { return delJSON(`${N(id)}/bookmarks/${bid}`); },

  // ── Translation overlays + contribute-back ──
  editBaseContent(id, number, content) { return putJSON(`${N(id)}/chapter/${number}/content`, { content }); },
  saveOverlay(id, number, content) { return putJSON(`${N(id)}/chapter/${number}/overlay`, { content }); },
  deleteOverlay(id, number) { return delJSON(`${N(id)}/chapter/${number}/overlay`); },
  selfTranslate(id, number) { return postJSON(`${N(id)}/chapter/${number}/self-translate`, {}); },
  resolveOverlay(id, number, choice, content) { return postJSON(`${N(id)}/chapter/${number}/resolve`, { choice, content: content || null }); },
  contribute(id, number) { return postJSON(`${N(id)}/chapter/${number}/contribute`, {}); },
  contributions(id, status) { return getJSON(`${N(id)}/contributions${status ? `?status=${status}` : ""}`); },
  acceptContribution(id, cid, content) {
    return postJSON(`${N(id)}/contributions/${cid}/accept`, content ? { content } : {});
  },
  rejectContribution(id, cid) { return postJSON(`${N(id)}/contributions/${cid}/reject`, {}); },

  // ── Tag suggestions ──
  suggestTags(id, tags, note) { return postJSON(`${N(id)}/tag-suggestions`, { tags, note: note || null }); },
  tagSuggestions(id, status) { return getJSON(`${N(id)}/tag-suggestions${status ? `?status=${status}` : ""}`); },
  acceptTagSuggestion(id, sid) { return postJSON(`${N(id)}/tag-suggestions/${sid}/accept`, {}); },
  rejectTagSuggestion(id, sid) { return postJSON(`${N(id)}/tag-suggestions/${sid}/reject`, {}); },

  // ── Audiobook TTS (narration) ──
  ttsVoices() { return getJSON(`${API_BASE}/tts/voices`); },
  generateChapterAudio(id, number, voiceId, force) {
    return postJSON(`${N(id)}/chapter/${number}/audio`, { voice_id: voiceId, force: !!force });
  },
  chapterAudioStatus(id, number, voiceId) {
    return getJSON(`${N(id)}/chapter/${number}/audio/status?voice_id=${encodeURIComponent(voiceId)}`);
  },
  generateBookAudio(id, voiceId, start, end) {
    return postJSON(`${N(id)}/audiobook`, { voice_id: voiceId, start: start ?? null, end: end ?? null });
  },
  bookAudioStatus(id, voiceId) {
    return getJSON(`${N(id)}/audiobook/status?voice_id=${encodeURIComponent(voiceId)}`);
  },
  ttsJob(jobId) { return getJSON(`${API_BASE}/tts/jobs/${jobId}`); },
  cancelTtsJob(jobId) { return postJSON(`${API_BASE}/tts/jobs/${jobId}/cancel`, {}); },
  audioCoverage(id) { return getJSON(`${N(id)}/audio/coverage`); },
  chapterAudioUrl(id, number, voiceId) {
    return `${N(id)}/chapter/${number}/audio.opus?voice_id=${encodeURIComponent(voiceId)}`;
  },

  // ── Translation + glossary ──
  translate(id, body) { return postJSON(`${N(id)}/translate`, body || {}); },
  glossary(id) { return getJSON(`${N(id)}/glossary`); },
  upsertGlossary(id, body) { return putJSON(`${N(id)}/glossary`, body); },
  delGlossary(id, tid) { return delJSON(`${N(id)}/glossary/${tid}`); },
  seedGlossary(id) { return postJSON(`${N(id)}/glossary/seed`, {}); },

  // ── Codex (novel-scoped) ──
  meta(id) { return getJSON(`${N(id)}/meta`); },
  stats(id, ceiling) { return getJSON(`${N(id)}/stats?ceiling=${ceiling}`); },
  async listEntities(id, ceiling, opts = {}) {
    const params = new URLSearchParams({ ceiling });
    if (opts.type) params.set("type", opts.type);
    if (opts.q) params.set("q", opts.q);
    const rows = await getJSON(`${N(id)}/entities?${params.toString()}`);
    return rows.map(mapEntity);
  },
  entityProfile(id, eid, ceiling) { return getJSON(`${N(id)}/entity/${eid}?ceiling=${ceiling}`); },
  relationships(id, eid, ceiling, otherId) {
    const params = new URLSearchParams({ ceiling });
    if (otherId != null) params.set("other_id", otherId);
    return getJSON(`${N(id)}/entity/${eid}/relationships?${params.toString()}`);
  },
  timeline(id, eid, ceiling) { return getJSON(`${N(id)}/entity/${eid}/timeline?ceiling=${ceiling}`); },
  identities(id, eid, ceiling) { return getJSON(`${N(id)}/entity/${eid}/identities?ceiling=${ceiling}`); },
  resolve(id, name, ceiling) { return getJSON(`${N(id)}/entity/resolve?name=${encodeURIComponent(name)}&ceiling=${ceiling}`); },
  ask(id, question, ceiling) { return postJSON(`${N(id)}/ask`, { question, ceiling }); },
  codexBuild(id, body) { return postJSON(`${N(id)}/codex/build`, body || {}); },
  mergeEntities(id, body) { return postJSON(`${N(id)}/merge-entities`, body); },

  // ── Product surfaces (home / activity / recap / health / cost estimate) ──
  home() { return getJSON(`${API_BASE}/home`); },
  activity(status, limit) {
    const p = new URLSearchParams();
    if (status) p.set("status", status);
    if (limit) p.set("limit", limit);
    const qs = p.toString();
    return getJSON(`${API_BASE}/activity${qs ? `?${qs}` : ""}`);
  },
  cancelActivity(row) {
    if (row.source === "tts") return this.cancelTtsJob(row.id);
    if (row.source === "import") return this.cancelImport(row.id);
    return this.cancelJob(row.id);
  },
  recap(id, ceiling) { return postJSON(`${N(id)}/recap`, ceiling != null ? { ceiling } : {}); },
  novelHealth(id, voiceId) {
    return getJSON(`${N(id)}/health${voiceId ? `?voice_id=${encodeURIComponent(voiceId)}` : ""}`);
  },
  costEstimate(id, action, params = {}) {
    const p = new URLSearchParams({ action });
    if (params.from_chapter != null) p.set("from_chapter", params.from_chapter);
    if (params.to_chapter != null) p.set("to_chapter", params.to_chapter);
    if (params.force) p.set("force", "true");
    if (params.voice_id) p.set("voice_id", params.voice_id);
    return getJSON(`${N(id)}/cost-estimate?${p.toString()}`);
  },

  // ── Job center (durable scrape/codex/translation jobs) ──
  jobs(opts = {}) {
    const params = new URLSearchParams();
    for (const k of ["kind", "status", "novel_id", "user_id", "limit"]) {
      if (opts[k] != null && opts[k] !== "") params.set(k, opts[k]);
    }
    if (opts.active) params.set("active", "1");
    const qs = params.toString();
    return getJSON(`${API_BASE}/jobs${qs ? `?${qs}` : ""}`);
  },
  job(jobId) { return getJSON(`${API_BASE}/jobs/${jobId}`); },
  cancelJob(jobId) { return postJSON(`${API_BASE}/jobs/${jobId}/cancel`, {}); },

  // ── File import (EPUB/PDF ingestion) ──
  uploadImport(file) {
    const fd = new FormData();
    fd.append("file", file);
    return postMultipart(`${API_BASE}/import/upload`, fd);
  },
  scanIncoming() { return postJSON(`${API_BASE}/import/scan-incoming`, {}); },
  batchImport(body) { return postJSON(`${API_BASE}/import/batch`, body || {}); },
  importJobs() { return getJSON(`${API_BASE}/import/jobs`); },
  importJob(jid) { return getJSON(`${API_BASE}/import/jobs/${jid}`); },
  updateImportPlan(jid, plan) { return putJSON(`${API_BASE}/import/jobs/${jid}/plan`, { plan }); },
  confirmOcr(jid, body) { return postJSON(`${API_BASE}/import/jobs/${jid}/confirm-ocr`, body || {}); },
  commitImport(jid, body) { return postJSON(`${API_BASE}/import/jobs/${jid}/commit`, body || {}); },
  commitSeries(jobIds) { return postJSON(`${API_BASE}/import/commit-series`, { job_ids: jobIds }); },
  cancelImport(jid) { return postJSON(`${API_BASE}/import/jobs/${jid}/cancel`, {}); },
  deleteImport(jid) { return delJSON(`${API_BASE}/import/jobs/${jid}`); },

  // Files above ~40 MB go up in chunks: init → PUT each slice → complete.
  CHUNKED_THRESHOLD: 40 * 1024 * 1024,
  CHUNK_SIZE: 8 * 1024 * 1024,
  async uploadChunked(file, onProgress) {
    const init = await postJSON(`${API_BASE}/import/upload/init`, { filename: file.name, size: file.size });
    const jid = init.id;
    let offset = 0;
    while (offset < file.size) {
      const end = Math.min(offset + this.CHUNK_SIZE, file.size);
      const res = await fetch(`${API_BASE}/import/upload/${jid}/chunk`, {
        method: "PUT",
        credentials: "include",
        headers: mutationHeaders({ "Upload-Offset": String(offset), "Content-Type": "application/octet-stream" }),
        body: file.slice(offset, end),
      });
      if (!res.ok) throw new Error(`Chunk upload failed at ${offset}`);
      const j = await res.json();
      offset = j.offset;
      if (onProgress) onProgress(offset / file.size);
    }
    return postJSON(`${API_BASE}/import/upload/${jid}/complete`, {});
  },
  async importFile(file, onProgress) {
    if (file.size > this.CHUNKED_THRESHOLD) return this.uploadChunked(file, onProgress);
    const r = await this.uploadImport(file);
    if (onProgress) onProgress(1);
    return r;
  },
};

export default API;
