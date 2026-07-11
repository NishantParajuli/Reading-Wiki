import { API_BASE, getJSON, postJSON } from "../../shared/api/http.js";
const novel = (id) => `${API_BASE}/novels/${id}`;
const portrait = { character: "PORTRAIT", location: "PLACE", faction: "EMBLEM", item: "OBJECT", concept: "CONCEPT", organization: "EMBLEM" };
const mapEntity = (entity) => ({
  id: entity.id,
  name: entity.canonical_name,
  type: entity.type,
  firstSeen: entity.first_seen_chapter,
  blurb: entity.description || "",
  portrait: entity.canonical_name
    ? `${portrait[entity.type] || "ENTRY"} — ${entity.canonical_name}`
    : (portrait[entity.type] || "ENTRY"),
});
export const codexApi = {
  meta: (id) => getJSON(`${novel(id)}/meta`),
  stats: (id, ceiling) => getJSON(`${novel(id)}/stats?ceiling=${ceiling}`),
  async listEntities(id, ceiling, opts = {}) {
    const params = new URLSearchParams({ ceiling });
    if (opts.type) params.set("type", opts.type);
    if (opts.q) params.set("q", opts.q);
    return (await getJSON(`${novel(id)}/entities?${params}`)).map(mapEntity);
  },
  entityProfile: (id, entityId, ceiling) => getJSON(`${novel(id)}/entity/${entityId}?ceiling=${ceiling}`),
  relationships(id, entityId, ceiling, otherId) {
    const params = new URLSearchParams({ ceiling });
    if (otherId != null) params.set("other_id", otherId);
    return getJSON(`${novel(id)}/entity/${entityId}/relationships?${params}`);
  },
  timeline: (id, entityId, ceiling) => getJSON(`${novel(id)}/entity/${entityId}/timeline?ceiling=${ceiling}`),
  identities: (id, entityId, ceiling) => getJSON(`${novel(id)}/entity/${entityId}/identities?ceiling=${ceiling}`),
  resolve: (id, name, ceiling) => getJSON(`${novel(id)}/entity/resolve?name=${encodeURIComponent(name)}&ceiling=${ceiling}`),
  ask: (id, question, ceiling) => postJSON(`${novel(id)}/ask`, { question, ceiling }),
  codexBuild: (id, body) => postJSON(`${novel(id)}/codex/build`, body || {}),
  mergeEntities: (id, body) => postJSON(`${novel(id)}/merge-entities`, body),
};
