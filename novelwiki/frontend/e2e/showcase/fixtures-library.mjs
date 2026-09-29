/* ============================================================
   Showcase extras for the catalog surfaces (Library, Discover).
   The real /api/discover returns `description`, `language` and
   `status_tags` for every shared novel; the base fixtures omit them for the
   shared titles (11–14), so the Discover featured strip has no blurbs to
   show. `withDiscoverExtras` fills those fields in. `bigLibrary` builds a
   large synthetic collection for density/performance review.
   All stories and people are invented for this fixture.
   ============================================================ */

export const discoverExtras = {
  11: {
    description: "A lighthouse keeper's daughter inherits a library that only opens at low tide. Every book in it is written in salt, and every book is about someone who drowned — until she finds one about herself.",
    language: "en", status_tags: ["ongoing", "mystery", "fantasy"],
  },
  12: {
    description: "The last ember of a fallen god sleeps inside a blacksmith's forge. When the empire comes to claim it, the smith's apprentice has one night to learn what fire remembers.",
    language: "ko", status_tags: ["ongoing", "action", "fantasy"],
  },
  13: {
    description: "In a village where the church bell rings once for every lie told within its hearing, a new priest arrives — and the bell will not stop ringing.",
    language: "en", status_tags: ["finished", "horror", "mystery"],
  },
  14: {
    description: "Tidewrights shape the sea with songs older than the continents. The youngest of them has lost her voice, and the ocean has started to forget its shape.",
    language: "zh", status_tags: ["ongoing", "adventure", "fantasy"],
  },
};

/** Fill in the fields the real discover projection always returns. */
export function withDiscoverExtras(items) {
  return (items || []).map(item => ({
    ...item,
    ...(discoverExtras[item.id] || {}),
    language: (discoverExtras[item.id] && discoverExtras[item.id].language) || item.language || item.original_language || null,
  }));
}

const EXTRA_TITLES = [
  ["The Lamplighter's Almanac", "Iris Penhallow"], ["Seven Bells for Winter", "Tobias Merrow"],
  ["Under the Glass Orchard", "Nell Aubade"], ["A Map of Quiet Rivers", "Hana Sorel"],
  ["The Ninth Tide", "Corin Vesper"], ["Salt and Starlight", "Maren Holt"],
  ["The Drowned Cartographer", "Ezra Fenn"], ["Nocturne for a Paper City", "Lio Marchetti"],
  ["The Heron King", "Aldous Crane"], ["Where the Lanterns Sleep", "Ottilie Grey"],
  ["The Clockmaker's Tide", "Felix Wyn"], ["Ashfall Letters", "Rowan Asher"],
];

/** A large synthetic library: the base novels plus generated-jacket extras. */
export function bigLibrary(novels, count = 60) {
  const shelves = ["reading", "to_read", "completed", null];
  const out = [...novels];
  for (let i = 0; out.length < count; i++) {
    const [title, author] = EXTRA_TITLES[i % EXTRA_TITLES.length];
    const round = Math.floor(i / EXTRA_TITLES.length);
    const chapters = 40 + ((i * 37) % 600);
    const shelf = shelves[i % shelves.length];
    const read = shelf === "completed" ? chapters : shelf === "reading" ? Math.floor(chapters * ((i % 7) + 1) / 9) : 0;
    out.push({
      id: 1000 + i, title: round ? `${title} ${round + 1}` : title, author, cover_url: null,
      description: null, chapter_count: chapters, min_chapter: 1, max_chapter: chapters,
      last_chapter: read ? Math.min(read + 1, chapters) : null, max_chapter_read: read,
      shelf, last_read_at: read ? new Date(Date.now() - (i + 1) * 5 * 3600e3).toISOString() : null,
      source_updated_at: new Date(Date.now() - (i % 9) * 86_400_000).toISOString(),
      new_chapters: i % 5 === 0 && read ? 2 + (i % 4) : 0,
      visibility: "private", can_edit: true, is_owner: true, codex_enabled: i % 3 === 0,
      original_language: "en", status_tags: [], audio_chapters: 0,
    });
  }
  return out;
}
