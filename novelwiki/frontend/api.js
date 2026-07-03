/* ============================================================
   api.js — backend client for the multi-novel reading platform.

   Everything is scoped to a novel id. The reader reads chapter `content`; the
   codex reads are additionally bounded by the server-computed effective ceiling
   for this reader. The browser may request a lower ceiling, but the backend
   clamps it to trusted read progress before any retrieval or synthesis happens.
   ============================================================ */
(function () {
  const API_BASE = "/api";
  const CSRF_COOKIE = "tg_csrf";
  const CSRF_HEADER = "X-Tideglass-CSRF";
  const REQUEST_HEADER = "X-Tideglass-Request";
  const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

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
    // credentials: "include" sends the session cookie (same-origin in prod; needed
    // for the cookie-based auth to work at all).
    const opts = { method, credentials: "include", headers: { Accept: "application/json" } };
    if (!SAFE_METHODS.has(method.toUpperCase())) mutationHeaders(opts.headers);
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body || {});
    }
    const res = await fetch(url, opts);
    if (!res.ok) {
      // A 401 on a normal call means the session lapsed mid-use — let the app re-gate.
      // Auth endpoints (e.g. /me when logged out) handle their own 401, so skip those.
      if (res.status === 401 && url.indexOf("/auth/") === -1 && window.__onUnauthorized) {
        try { window.__onUnauthorized(); } catch (e) {}
      }
      let detail = `${res.status} ${res.statusText}`;
      try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    if (res.status === 204) return null;
    return res.json();
  }
  const getJSON = (url) => req("GET", url);
  const postJSON = (url, body) => req("POST", url, body || {});
  const putJSON = (url, body) => req("PUT", url, body || {});
  const delJSON = (url) => req("DELETE", url);

  const TYPE_PORTRAIT = {
    character: "PORTRAIT", location: "PLACE", faction: "EMBLEM",
    item: "OBJECT", concept: "CONCEPT", organization: "EMBLEM",
  };
  function portraitLabel(type, name) {
    const p = TYPE_PORTRAIT[type] || "ENTRY";
    return name ? `${p} — ${name}` : p;
  }
  function mapEntity(e) {
    return {
      id: e.id,
      name: e.canonical_name,
      type: e.type,
      firstSeen: e.first_seen_chapter,
      blurb: e.description || "",
      portrait: portraitLabel(e.type, e.canonical_name),
    };
  }

  const N = (id) => `${API_BASE}/novels/${id}`;

  const API = {
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

    // ── Profiles / account (Phase 3) ──
    profile(username) { return getJSON(`${API_BASE}/users/${encodeURIComponent(username)}`); },
    updateMe(body) { return req("PATCH", `${API_BASE}/me`, body); },
    async uploadAvatar(file) {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_BASE}/me/avatar`, {
        method: "POST",
        credentials: "include",
        headers: mutationHeaders(),
        body: fd,
      });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
        const err = new Error(detail); err.status = res.status; throw err;
      }
      return res.json();
    },

    // ── Admin dashboard (Phase 4) ──
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
    },

    // ── Library / novels ──
    adapters() { return getJSON(`${API_BASE}/adapters`); },
    novels() { return getJSON(`${API_BASE}/novels`); },
    createNovel(body) { return postJSON(`${API_BASE}/novels`, body); },
    novel(id) { return getJSON(N(id)); },
    updateNovel(id, body) { return req("PATCH", N(id), body); },
    deleteNovel(id) { return delJSON(N(id)); },
    // Discovery, per-user library membership, visibility, and quota usage.
    discover(q) { return getJSON(`${API_BASE}/discover${q ? `?q=${encodeURIComponent(q)}` : ""}`); },
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

    // ── Translation overlays + contribute-back (Phase 5) ──
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

    // ── Tag suggestions (reader proposes owner/admin-controlled novel tags) ──
    suggestTags(id, tags, note) { return postJSON(`${N(id)}/tag-suggestions`, { tags, note: note || null }); },
    tagSuggestions(id, status) { return getJSON(`${N(id)}/tag-suggestions${status ? `?status=${status}` : ""}`); },
    acceptTagSuggestion(id, sid) { return postJSON(`${N(id)}/tag-suggestions/${sid}/accept`, {}); },
    rejectTagSuggestion(id, sid) { return postJSON(`${N(id)}/tag-suggestions/${sid}/reject`, {}); },

    // ── Audiobook TTS (narration) ──
    ttsVoices() { return getJSON(`${API_BASE}/tts/voices`); },
    // Per-chapter: returns {status:"ready",cached:true,...} if already generated, else {status:"queued",job_id}.
    generateChapterAudio(id, number, voiceId, force) {
      return postJSON(`${N(id)}/chapter/${number}/audio`, { voice_id: voiceId, force: !!force });
    },
    chapterAudioStatus(id, number, voiceId) {
      return getJSON(`${N(id)}/chapter/${number}/audio/status?voice_id=${encodeURIComponent(voiceId)}`);
    },
    // Bounded, cancellable whole-book batch (skips already-cached chapters; capped server-side).
    generateBookAudio(id, voiceId, start, end) {
      return postJSON(`${N(id)}/audiobook`, { voice_id: voiceId, start: start ?? null, end: end ?? null });
    },
    bookAudioStatus(id, voiceId) {
      return getJSON(`${N(id)}/audiobook/status?voice_id=${encodeURIComponent(voiceId)}`);
    },
    ttsJob(jobId) { return getJSON(`${API_BASE}/tts/jobs/${jobId}`); },
    cancelTtsJob(jobId) { return postJSON(`${API_BASE}/tts/jobs/${jobId}/cancel`, {}); },
    // Chapters that already have shared audio in a voice (drives TOC speaker icons).
    novelAudioChapters(id, voiceId) {
      return getJSON(`${N(id)}/audio/chapters?voice_id=${encodeURIComponent(voiceId)}`);
    },
    // The <audio src> URL for a chapter's narration (access-controlled, range-capable).
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

    // ── Job center (durable scrape/codex/translation jobs) ──
    // Non-admins only ever see their own jobs; pass filters (kind/status/novel_id/active) as opts.
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
    // uploadImport posts multipart (FormData), not JSON, so it bypasses the req() helper.
    async uploadImport(file) {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_BASE}/import/upload`, {
        method: "POST",
        credentials: "include",
        headers: mutationHeaders(),
        body: fd,
      });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
        const err = new Error(detail); err.status = res.status; throw err;
      }
      return res.json();
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

    // Files above ~40 MB can't ride a single POST through the tunnel, so they go up in
    // chunks: init → PUT each slice at its byte offset → complete. `onProgress(frac)` drives
    // a progress bar; a dropped connection can resume from GET .../status.
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
    // One entry point the UI calls regardless of size: small files go single-shot, big ones chunked.
    async importFile(file, onProgress) {
      if (file.size > this.CHUNKED_THRESHOLD) return this.uploadChunked(file, onProgress);
      const r = await this.uploadImport(file);
      if (onProgress) onProgress(1);
      return r;
    },
  };

  function buildCiteMap(citations) {
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

  window.API = API;
  window.mapEntity = mapEntity;
  window.portraitLabel = portraitLabel;
  window.buildCiteMap = buildCiteMap;
  window.NOVEL = { meta: { title: "Codex", blurb: "", totalChapters: 1 }, entities: [] };
})();
