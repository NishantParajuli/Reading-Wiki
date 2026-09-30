/* ============================================================
   Extra showcase states for the novel surface (hero, Overview, Chapters,
   Manage). Optional: wrap the router to add them —

     import { withNovelStates } from "./fixtures-novel.mjs";
     const route = withNovelStates(respond);   // then call route(method, path, query)

   · /n/3/manage   — the owner inbox: a contribution with a diff and a tag
                      suggestion, so Manage opens with its Inbox section.
   · /n/15         — a book whose source hasn't been scraped yet (no chapters).
   · /n/16         — a very long title + author, to review type scaling.
   All stories, people and text are invented for the fixture.
   ============================================================ */
import { novelDetail, chapterList } from "./fixtures.mjs";

const EMPTY_BOOK = {
  id: 15, title: "The Unwritten Harbor", author: "Ines Calder", cover_url: null,
  description: "A harbor town waits for a ship that the maps insist has already arrived.",
  chapter_count: 0, min_chapter: null, max_chapter: null, visibility: "private", can_edit: true, is_owner: true,
  codex_enabled: false, original_language: "en", translation_type: "translated", status_tags: ["ongoing", "mystery"],
  contribution_policy: "manual", shelf: "to_read", can_suggest_tags: false,
  sources: [{ id: 115, adapter: "royalroad", label: "Royal Road", start_url: "https://example.test/fiction/15", language: "en", is_raw: false, chapter_offset: 0, last_scraped_at: null }],
  progress: { last_chapter: null, max_chapter_read: null, scroll_pct: 0 },
  provenance: { scraped: true },
};

const LONG_TITLE_BOOK = (() => {
  const base = novelDetail(9);
  return {
    ...base, id: 16, cover_url: null,
    title: "I Was Reincarnated as the Villainess's Younger Brother, but the Northern Duke Keeps Mistaking Me for Someone Else",
    author: "Seo Haneul-Ahreum",
  };
})();

export function withNovelStates(respond) {
  return (method, path, query) => {
    if (path === "/api/novels/3/contributions") {
      return [{
        id: 1, chapter: 12, from_display_name: "Ari", from_username: "ari", is_conflict: false,
        base_content: "The tide came in without a sound.\nShe waited at the glass.",
        content: "The tide came in without a sound.\nShe waited at the glass, breath held, counting the bells.",
      }];
    }
    if (path === "/api/novels/3/tag-suggestions") {
      return [{ id: 3, from_display_name: "Sol", from_username: "sol", tags: ["finished", "adventure", "mystery"], note: "The ending reads as a mystery more than an adventure." }];
    }
    const book = path.match(/^\/api\/novels\/(15|16)(\/.*)?$/);
    if (book) {
      const id = Number(book[1]);
      const rest = book[2] || "";
      const detail = id === 15 ? EMPTY_BOOK : LONG_TITLE_BOOK;
      if (!rest) return detail;
      if (rest === "/chapters") return id === 15 ? [] : chapterList(9);
      if (rest === "/progress") return detail.progress;
      return respond(method, `/api/novels/${id === 15 ? 13 : 9}${rest}`, query);
    }
    return respond(method, path, query);
  };
}
