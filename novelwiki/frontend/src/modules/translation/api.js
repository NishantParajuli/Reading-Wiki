import { API_BASE, delJSON, getJSON, postJSON, putJSON } from "../../shared/api/http.js";
const novel = (id) => `${API_BASE}/novels/${id}`;
export const translationApi = {
  translate: (id, body) => postJSON(`${novel(id)}/translate`, body || {}),
  glossary: (id) => getJSON(`${novel(id)}/glossary`),
  upsertGlossary: (id, body) => putJSON(`${novel(id)}/glossary`, body),
  delGlossary: (id, termId) => delJSON(`${novel(id)}/glossary/${termId}`),
  seedGlossary: (id) => postJSON(`${novel(id)}/glossary/seed`, {}),
};
