import { API_BASE, delJSON, getJSON, postJSON, putJSON } from "../../shared/api/http.js";

const novel = (id) => `${API_BASE}/novels/${id}`;
export const readingApi = {
  chapters: (id) => getJSON(`${novel(id)}/chapters`),
  chapter: (id, number) => getJSON(`${novel(id)}/chapter/${number}`),
  getProgress: (id) => getJSON(`${novel(id)}/progress`),
  setProgress: (id, body) => putJSON(`${novel(id)}/progress`, body),
  bookmarks: (id) => getJSON(`${novel(id)}/bookmarks`),
  addBookmark: (id, body) => postJSON(`${novel(id)}/bookmarks`, body),
  delBookmark: (id, bookmarkId) => delJSON(`${novel(id)}/bookmarks/${bookmarkId}`),
  editBaseContent: (id, number, content) => putJSON(`${novel(id)}/chapter/${number}/content`, { content }),
  saveOverlay: (id, number, content) => putJSON(`${novel(id)}/chapter/${number}/overlay`, { content }),
  deleteOverlay: (id, number) => delJSON(`${novel(id)}/chapter/${number}/overlay`),
  selfTranslate: (id, number) => postJSON(`${novel(id)}/chapter/${number}/self-translate`, {}),
  resolveOverlay: (id, number, choice, content) => postJSON(
    `${novel(id)}/chapter/${number}/resolve`, { choice, content: content || null },
  ),
  contribute: (id, number) => postJSON(`${novel(id)}/chapter/${number}/contribute`, {}),
  contributions: (id, status) => getJSON(`${novel(id)}/contributions${status ? `?status=${status}` : ""}`),
  acceptContribution: (id, contributionId, content) => postJSON(
    `${novel(id)}/contributions/${contributionId}/accept`, content ? { content } : {},
  ),
  rejectContribution: (id, contributionId) => postJSON(`${novel(id)}/contributions/${contributionId}/reject`, {}),
};
