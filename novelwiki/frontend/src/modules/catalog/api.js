import { API_BASE, delJSON, getJSON, postJSON, postMultipart, req } from "../../shared/api/http.js";

const novel = (id) => `${API_BASE}/novels/${id}`;
export const catalogApi = {
  novels: () => getJSON(`${API_BASE}/novels`),
  novel: (id) => getJSON(novel(id)),
  createNovel: (body) => postJSON(`${API_BASE}/novels`, body),
  updateNovel: (id, body) => req("PATCH", novel(id), body),
  deleteNovel: (id) => delJSON(novel(id)),
  addToLibrary: (id) => postJSON(`${novel(id)}/library`, {}),
  removeFromLibrary: (id) => delJSON(`${novel(id)}/library`),
  setVisibility: (id, visibility) => req("PATCH", `${novel(id)}/visibility`, { visibility }),
  uploadNovelCover(id, file) {
    const form = new FormData(); form.append("file", file);
    return postMultipart(`${novel(id)}/cover`, form);
  },
};
