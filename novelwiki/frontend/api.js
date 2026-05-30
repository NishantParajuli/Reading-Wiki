/* ============================================================
   api.js — backend client + adapters (replaces the demo data.js)

   Spoiler-safety note: this layer NEVER requests unbounded data. Every read
   carries the chapter ceiling, and the server applies `WHERE chapter <= ceiling`
   in SQL — so no chapter > N data ever reaches the browser. The "locked / not
   yet revealed" visuals are therefore purely decorative teasers fed by NOTHING
   real (see Browser/Entity). That keeps THE ONE INVARIANT true by construction.
   ============================================================ */
(function () {
  const API_BASE = "/api";

  async function getJSON(url) {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try { const j = await res.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  // Striped placeholder caption that mirrors the demo's portrait labels.
  const TYPE_PORTRAIT = {
    character: "PORTRAIT", location: "PLACE", faction: "EMBLEM",
    item: "OBJECT", concept: "CONCEPT", organization: "EMBLEM",
  };
  function portraitLabel(type, name) {
    const p = TYPE_PORTRAIT[type] || "ENTRY";
    return name ? `${p} — ${name}` : p;
  }

  // Backend entity (list item OR profile) → the shape the cards/pages expect.
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

  const API = {
    base: API_BASE,

    meta() { return getJSON(`${API_BASE}/meta/chapters`); },
    stats(ceiling) { return getJSON(`${API_BASE}/meta/stats?ceiling=${ceiling}`); },

    async listEntities(ceiling, opts = {}) {
      const params = new URLSearchParams({ ceiling });
      if (opts.type) params.set("type", opts.type);
      if (opts.q) params.set("q", opts.q);
      const rows = await getJSON(`${API_BASE}/entities?${params.toString()}`);
      return rows.map(mapEntity);
    },

    entityProfile(id, ceiling) {
      return getJSON(`${API_BASE}/entity/${id}?ceiling=${ceiling}`);
    },
    relationships(id, ceiling, otherId) {
      const params = new URLSearchParams({ ceiling });
      if (otherId != null) params.set("other_id", otherId);
      return getJSON(`${API_BASE}/entity/${id}/relationships?${params.toString()}`);
    },
    timeline(id, ceiling) {
      return getJSON(`${API_BASE}/entity/${id}/timeline?ceiling=${ceiling}`);
    },
    identities(id, ceiling) {
      return getJSON(`${API_BASE}/entity/${id}/identities?ceiling=${ceiling}`);
    },
    resolve(name, ceiling) {
      return getJSON(`${API_BASE}/entity/resolve?name=${encodeURIComponent(name)}&ceiling=${ceiling}`);
    },

    ask(question, ceiling) {
      return postJSON(`${API_BASE}/ask`, { question, chapter_ceiling: ceiling });
    },

    admin: {
      scrape: (body) => postJSON(`${API_BASE}/admin/scrape`, body),
      chunk: (body) => postJSON(`${API_BASE}/admin/chunk`, body),
      embed: (body) => postJSON(`${API_BASE}/admin/embed`, body),
      extract: (body) => postJSON(`${API_BASE}/admin/extract`, body),
      rebuildBm25: () => postJSON(`${API_BASE}/admin/rebuild-bm25`, {}),
      mergeEntities: (body) => postJSON(`${API_BASE}/admin/merge-entities`, body),
    },
  };

  // Build a lookup from the /ask citations array, keyed by `${kind}:${id}`, so
  // inline tokens like "[Chunk 12, Chapter 5]" can be turned into clickable sups.
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

  // Display-only meta; App fills `meta` after the first /meta/chapters call.
  // Kept on window so legacy references in the design components don't throw.
  window.NOVEL = { meta: { title: "Codex", blurb: "", totalChapters: 1 }, entities: [] };
})();
