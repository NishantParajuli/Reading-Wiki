/* ============================================================
   api.js — backend client for the multi-novel reading platform.

   Everything is scoped to a novel id. The reader reads chapter `content`; the
   codex reads are additionally bounded by the chapter ceiling, and the server
   applies `WHERE chapter <= ceiling AND novel_id = ...` in SQL — so no future
   data and no other novel's data ever reaches the browser.
   ============================================================ */
(function () {
  const API_BASE = "/api";

  async function req(method, url, body) {
    const opts = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body || {});
    }
    const res = await fetch(url, opts);
    if (!res.ok) {
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

    // ── Library / novels ──
    adapters() { return getJSON(`${API_BASE}/adapters`); },
    novels() { return getJSON(`${API_BASE}/novels`); },
    createNovel(body) { return postJSON(`${API_BASE}/novels`, body); },
    novel(id) { return getJSON(N(id)); },
    updateNovel(id, body) { return req("PATCH", N(id), body); },
    deleteNovel(id) { return delJSON(N(id)); },
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
