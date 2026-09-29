/* ============================================================
   Showcase fixtures — a synthetic, fully-populated Tideglass instance for
   visual review. Every /api route the SPA calls is answered here, so screens
   can be rendered with realistic data without a backend or real accounts.
   All stories, people and text are invented for this fixture.
   ============================================================ */

const DAY = 86_400_000;
const now = Date.now();
const iso = (msAgo) => new Date(now - msAgo).toISOString();

export const user = {
  id: 1, username: "nishant", display_name: "Nishant", role: "admin", status: "active",
  email: "reader@example.test", email_verified: true, avatar_url: null, bio: "Night reader. Collector of long stories.",
  prefs: {}, created_at: iso(420 * DAY),
  ai_backends: {
    agy: { enabled: false, workloads: [] },
    openai_codex: { enabled: true, workloads: ["translate_batch", "codex_extract"], default_backend: "openai_codex" },
  },
};

/* ---------- cover art (SVG, served same-origin so palettes can be read) ---------- */
const COVER_ART = {
  1: { a: "#0b1d3a", b: "#1f5f8b", c: "#bfe9ff", motif: "moon" },
  2: { a: "#2a0f08", b: "#b4461f", c: "#ffd08a", motif: "lantern" },
  3: { a: "#10241c", b: "#2f7a5c", c: "#e8f5c8", motif: "map" },
  4: { a: "#16161f", b: "#5a4a8a", c: "#e7dcff", motif: "stars" },
  5: { a: "#2b0b1c", b: "#8a2a55", c: "#ffc2d9", motif: "orchard" },
  7: { a: "#1a1208", b: "#9a6b1c", c: "#ffe6a6", motif: "crown" },
  8: { a: "#07232a", b: "#157a86", c: "#b9fff5", motif: "gears" },
  10: { a: "#1b0d2e", b: "#6b3fb8", c: "#f1d6ff", motif: "sword" },
  12: { a: "#2e1206", b: "#c2410c", c: "#ffd7a1", motif: "ember" },
};

function motifSvg(m, c) {
  switch (m) {
    case "moon": return `<circle cx="140" cy="80" r="34" fill="${c}"/><circle cx="140" cy="80" r="70" fill="${c}" opacity=".12"/>${[0, 1, 2, 3, 4].map(i => `<path d="M0 ${200 + i * 20} Q50 ${190 + i * 20} 100 ${200 + i * 20} T200 ${200 + i * 20} V300 H0Z" fill="#0a1a33" opacity="${0.35 + i * 0.12}"/>`).join("")}${[0, 1, 2, 3, 4, 5].map(i => `<rect x="${120 - i * 3}" y="${205 + i * 11}" width="${40 - i * 4}" height="2" fill="${c}" opacity="${0.7 - i * 0.1}"/>`).join("")}`;
    case "lantern": return `<rect x="84" y="90" width="32" height="46" rx="8" fill="${c}"/><rect x="92" y="80" width="16" height="10" fill="${c}" opacity=".8"/><circle cx="100" cy="113" r="60" fill="${c}" opacity=".18"/>${Array.from({ length: 40 }, (_, i) => `<line x1="${(i * 37) % 200}" y1="${(i * 53) % 300}" x2="${(i * 37) % 200 - 4}" y2="${(i * 53) % 300 + 16}" stroke="${c}" stroke-opacity=".35"/>`).join("")}`;
    case "map": return `${Array.from({ length: 7 }, (_, i) => `<path d="M${20 + i * 22} 60 C${60 + i * 10} ${120 + i * 8} ${10 + i * 20} ${170} ${40 + i * 18} 250" stroke="${c}" stroke-opacity=".4" fill="none"/>`).join("")}<circle cx="120" cy="150" r="6" fill="${c}"/><path d="M60 230 l20 -20 l20 20 l20 -30 l20 30" stroke="${c}" fill="none" stroke-width="2"/>`;
    case "stars": return `${Array.from({ length: 60 }, (_, i) => `<circle cx="${(i * 71) % 200}" cy="${(i * 43) % 300}" r="${(i % 3) * 0.6 + 0.4}" fill="${c}" opacity="${0.4 + (i % 5) * 0.12}"/>`).join("")}<path d="M100 60 L106 140 L100 240 L94 140Z" fill="${c}" opacity=".85"/>`;
    case "orchard": return `${Array.from({ length: 5 }, (_, i) => `<circle cx="${30 + i * 36}" cy="${170 - (i % 2) * 20}" r="${26 + (i % 3) * 6}" fill="#3d0f25" opacity=".85"/><rect x="${27 + i * 36}" y="${180 - (i % 2) * 20}" width="6" height="70" fill="#1c0710"/>`).join("")}<circle cx="100" cy="70" r="26" fill="${c}"/>`;
    case "crown": return `<path d="M50 170 L60 110 L85 145 L100 95 L115 145 L140 110 L150 170Z" fill="${c}"/><rect x="50" y="170" width="100" height="14" fill="${c}" opacity=".85"/><circle cx="100" cy="150" r="80" fill="${c}" opacity=".08"/>`;
    case "gears": return `${[0, 1, 2].map(i => `<circle cx="${60 + i * 45}" cy="${130 + (i % 2) * 40}" r="${30 - i * 4}" fill="none" stroke="${c}" stroke-width="6" stroke-dasharray="6 5" opacity=".75"/>`).join("")}<path d="M0 230 Q50 215 100 230 T200 230 V300 H0Z" fill="${c}" opacity=".25"/>`;
    case "sword": return `<rect x="97" y="40" width="6" height="170" fill="${c}"/><rect x="75" y="200" width="50" height="8" rx="3" fill="${c}"/><rect x="96" y="208" width="8" height="34" fill="${c}" opacity=".8"/><circle cx="100" cy="120" r="75" fill="${c}" opacity=".1"/>`;
    case "ember": return `${Array.from({ length: 50 }, (_, i) => `<circle cx="${(i * 67) % 200}" cy="${300 - ((i * 29) % 260)}" r="${(i % 4) * 0.8 + 0.6}" fill="${c}" opacity="${0.3 + (i % 6) * 0.11}"/>`).join("")}<path d="M100 250 C60 200 90 170 100 120 C110 170 140 200 100 250Z" fill="${c}" opacity=".9"/>`;
    default: return "";
  }
}

export function coverSvg(id, title, author) {
  const art = COVER_ART[id];
  if (!art) return null;
  const words = title.split(" ");
  const lines = [];
  let line = "";
  for (const w of words) { if ((line + " " + w).trim().length > 14) { lines.push(line.trim()); line = w; } else line += " " + w; }
  lines.push(line.trim());
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 300" width="400" height="600">
  <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${art.b}"/><stop offset="1" stop-color="${art.a}"/></linearGradient></defs>
  <rect width="200" height="300" fill="url(#g)"/>${motifSvg(art.motif, art.c)}
  ${lines.map((l, i) => `<text x="100" y="${258 - (lines.length - 1 - i) * 20}" text-anchor="middle" font-family="Georgia, serif" font-size="17" fill="${art.c}" letter-spacing="0.5">${l}</text>`).join("")}
  <text x="100" y="286" text-anchor="middle" font-family="Helvetica, Arial" font-size="7" letter-spacing="2.5" fill="${art.c}" opacity=".8">${(author || "").toUpperCase()}</text>
  </svg>`;
}

const coverUrl = (id) => (COVER_ART[id] ? `/api/mock-covers/${id}.svg` : null);

/* ---------- the library ---------- */
const BOOKS = [
  { id: 1, title: "The Glass Tide", author: "Elena Marsh", chapters: 240, read: 118, shelf: "reading", lastRead: 2 * 3600e3, audio: 60, codex: true, lang: "en", genre: ["fantasy", "mystery"], desc: "When the tide pulls back from the glass shore, Mira finds a city that should not exist — and a letter addressed to her, written two hundred years before she was born.\n\nA slow-burning mystery of drowned archives, borrowed names and a sea that remembers everything it has ever touched." },
  { id: 2, title: "A Lantern in the Rain", author: "Julian Wren", chapters: 186, read: 41, shelf: "reading", lastRead: 1.2 * DAY, audio: 0, codex: true, lang: "en", genre: ["drama", "romance"], desc: "A lamplighter in a city of endless rain keeps a list of every window that stays dark." },
  { id: 3, title: "The Cartographer's Daughter", author: "M. A. Wilder", chapters: 312, read: 312, shelf: "completed", lastRead: 9 * DAY, audio: 0, codex: true, lang: "ja", genre: ["adventure", "fantasy"], desc: "Every map her father drew came true. The last one shows a coastline no one has seen." },
  { id: 4, title: "Letters from the North", author: "Clara Finch", chapters: 94, read: 12, shelf: "reading", lastRead: 3 * DAY, audio: 12, codex: false, lang: "en", genre: ["slice_of_life"], desc: "Seasons of correspondence between a lighthouse keeper and a stranger who writes back." },
  { id: 5, title: "The Orchard at Midnight", author: "Theo Ashford", chapters: 240, read: 0, shelf: "to_read", lastRead: null, audio: 0, codex: false, lang: "ko", genre: ["horror", "mystery"], desc: "The fruit ripens only in the dark, and the orchard keeps whoever eats it." },
  { id: 6, title: "An Ocean Between Us", author: "June Okada", chapters: 270, read: 0, shelf: "to_read", lastRead: null, audio: 0, codex: false, lang: "zh", genre: ["romance"], desc: "Two translators, one untranslatable word." },
  { id: 7, title: "Ashes of the Ninth Crown", author: "Rhea Castellan", chapters: 1432, read: 604, shelf: "reading", lastRead: 5 * 3600e3, audio: 220, codex: true, lang: "zh", genre: ["action", "fantasy"], desc: "Nine crowns forged from a fallen star. Eight are accounted for." },
  { id: 8, title: "The Clockwork Sea", author: "Idris Vale", chapters: 88, read: 88, shelf: "completed", lastRead: 30 * DAY, audio: 88, codex: true, lang: "en", genre: ["sci_fi", "adventure"], desc: "A submarine city runs on a clock no one remembers winding." },
  { id: 9, title: "Moonlit Archive", author: "Sable Ren", chapters: 57, read: 3, shelf: "to_read", lastRead: 14 * DAY, audio: 0, codex: false, lang: "en", genre: ["mystery"], desc: "The library opens only under a full moon, and it is always overdue." },
  { id: 10, title: "Sword of the Quiet Star", author: "Kaito Arima", chapters: 402, read: 210, shelf: "reading", lastRead: 6 * DAY, audio: 0, codex: true, lang: "ja", genre: ["action", "adventure"], desc: "A swordsman who has never drawn his blade in anger is asked to end a war." },
];

const SHARED = [
  { id: 11, title: "The Salt Library", author: "Wren Halloway", chapters: 130, lang: "en", codex: true, audio: true, tt: "translated" },
  { id: 12, title: "Emberfall", author: "Oren Blackwood", chapters: 764, lang: "ko", codex: true, audio: false, tt: "raws+translated" },
  { id: 13, title: "The Hollow Bell", author: "Mara Quill", chapters: 45, lang: "en", codex: false, audio: false, tt: null },
  { id: 14, title: "Tidewrights", author: "Pell Aurin", chapters: 210, lang: "zh", codex: true, audio: true, tt: "translated" },
];

function novelSummary(b) {
  return {
    id: b.id, title: b.title, author: b.author, cover_url: coverUrl(b.id), description: b.desc,
    chapter_count: b.chapters, min_chapter: 1, max_chapter: b.chapters,
    last_chapter: b.read ? Math.min(b.read + 1, b.chapters) : null, max_chapter_read: b.read,
    shelf: b.shelf, last_read_at: b.lastRead != null ? iso(b.lastRead) : null,
    source_updated_at: iso((b.id % 5) * DAY), new_chapters: b.id === 7 ? 6 : b.id === 2 ? 3 : 0,
    visibility: b.id % 3 === 0 ? "global" : b.id % 2 ? "private" : "public", can_edit: true, is_owner: true,
    codex_enabled: b.codex, original_language: b.lang, status_tags: [b.chapters > 300 ? "ongoing" : "finished", ...b.genre],
    audio_chapters: b.audio,
  };
}

export const novels = BOOKS.map(novelSummary);

export function novelDetail(id) {
  const b = BOOKS.find(x => x.id === id);
  if (!b) {
    const s = SHARED.find(x => x.id === id);
    if (!s) return null;
    return {
      id: s.id, title: s.title, author: s.author, cover_url: coverUrl(s.id), description: "A story from the shared library.",
      chapter_count: s.chapters, min_chapter: 1, max_chapter: s.chapters, visibility: "global", can_edit: false, is_owner: false,
      codex_enabled: s.codex, original_language: s.lang, translation_type: s.tt, status_tags: ["ongoing", "fantasy"],
      sources: [], progress: { last_chapter: null, max_chapter_read: 0, scroll_pct: 0 }, shelf: null, can_suggest_tags: true,
      provenance: { scraped: true, translated: s.lang !== "en" },
    };
  }
  return {
    ...novelSummary(b),
    translation_type: b.lang === "en" ? "translated" : "raws+translated",
    contribution_policy: "manual",
    can_suggest_tags: false,
    sources: [
      { id: 100 + id, adapter: "royalroad", label: "Royal Road", start_url: `https://example.test/fiction/${id}`, language: "en", is_raw: false, chapter_offset: 0 },
      ...(b.lang !== "en" ? [{ id: 200 + id, adapter: "raw-site", label: "Raw source", start_url: `https://raw.example.test/${id}`, language: b.lang, is_raw: true, chapter_offset: -1 }] : []),
    ],
    progress: { last_chapter: b.read ? Math.min(b.read + 1, b.chapters) : null, max_chapter_read: b.read, scroll_pct: 0.35 },
    provenance: { scraped: true, translated: b.lang !== "en", user_edited: id === 1, imported: id === 4 },
  };
}

/* ---------- chapters ---------- */
const TITLES = ["Arrival", "The Glass Shore", "Undertow", "Salt Letters", "A City Beneath", "The Archivist", "Borrowed Names", "Low Water", "The Bell Tower", "What the Sea Keeps", "Lanterns", "The Drowned Stair", "An Unsent Reply", "Moon Tide", "The Cartographer", "Quiet Hours", "The Second Door", "Keeper of Keys", "Riptide", "Glasswork"];

export function chapterList(id) {
  const n = (novelDetail(id) || { chapter_count: 40 }).chapter_count;
  const count = Math.min(n, 400);
  return Array.from({ length: count }, (_, i) => {
    const number = i + 1;
    const vol = Math.floor(i / 60) + 1;
    return {
      number, title: TITLES[i % TITLES.length] + (i >= TITLES.length ? ` ${Math.floor(i / TITLES.length) + 1}` : ""),
      kind: "chapter", part_label: id === 7 || id === 1 ? `Volume ${vol}: ${["The Shore", "Undertow", "Deep Water", "The Archive", "High Tide", "Moonrise", "Return"][vol - 1] || "Beyond"}` : null,
      has_content: true, translation_status: number > n - 3 ? "pending" : "done",
    };
  });
}

const PROSE = [
  "Mira reached the glass shore an hour before dawn, when the tide was so far out that the sea had become a rumour. The sand gave way to something smoother, cooler — a floor of pale, clouded glass that ran toward the horizon and caught the last of the moonlight like a held breath.",
  "She had come for an answer. The village behind her had offered only questions, wrapped in salt air and the patient sound of bells that no one admitted to ringing.",
  "Beneath the glass, shapes moved. Not fish, and not quite shadows: rooftops, she realised, and the long curve of a street, and a square with a fountain that had not seen air in two hundred years. The city lay perfectly preserved beneath the surface, lit from somewhere below by a light the colour of the inside of a shell.",
  "“You’re early,” said a voice behind her.",
  "The archivist was a small woman in a coat several sizes too large, and she carried a lantern that gave no heat. She looked at Mira the way one looks at a word in a language one almost remembers.",
  "“The tide turns at first light,” the archivist went on. “When it does, the door opens for eleven minutes. After that, whatever is inside stays inside until the next low water. Some people wait a year. Some people wait longer.”",
  "Mira thought of the letter in her pocket — the paper soft with handling, the ink gone the brown of old tea. It had been addressed to her by name, in a hand she did not recognise, and dated long before her grandmother was born.",
  "“And if I go in,” she said, “will I come out?”",
  "The archivist smiled, not unkindly. “Everyone comes out,” she said. “The question is always who.”",
  "Far out on the flats, the first thin line of silver appeared where the sea was beginning its return. The glass beneath their feet began, very faintly, to hum.",
  "Mira did not remember deciding. She only remembered the cold of the handle, the give of a door that should have been too heavy, and the smell that rose to meet her: paper, and brine, and something like rain on warm stone.",
  "Behind her the tide came in, soft as a turning page.",
];

export function chapter(id, number) {
  const list = chapterList(id);
  const max = list.length;
  const t = list[number - 1];
  const content = PROSE.join("\n\n");
  return {
    number, title: t ? t.title : `Chapter ${number}`, content, rich_html: null,
    prev: number > 1 ? number - 1 : null, next: number < max ? number + 1 : null,
    next_title: list[number] ? list[number].title : null, prev_title: list[number - 2] ? list[number - 2].title : null,
    next_is_raw: false, word_count: content.split(/\s+/).length * 3,
    overlay: null, overlay_conflict: false, is_raw: false, can_edit_base: true, is_owner: true, has_original: false,
    provenance: { scraped: true, translated: id !== 1 },
  };
}

/* ---------- codex ---------- */
export const entities = [
  { id: 1, canonical_name: "Mira Vale", type: "character", first_seen_chapter: 1, description: "A cartographer's apprentice who follows a two-hundred-year-old letter to the glass shore." },
  { id: 2, canonical_name: "The Archivist", type: "character", first_seen_chapter: 1, description: "Keeper of the drowned library; speaks as if she has met everyone before." },
  { id: 3, canonical_name: "The Glass Shore", type: "location", first_seen_chapter: 1, description: "A tidal flat of clouded glass that reveals a sunken city at low water." },
  { id: 4, canonical_name: "Saltmere", type: "location", first_seen_chapter: 2, description: "The fishing village above the shore, where the bells ring by themselves." },
  { id: 5, canonical_name: "The Order of Low Water", type: "faction", first_seen_chapter: 6, description: "Tide-watchers who record every opening of the door." },
  { id: 6, canonical_name: "The Unsent Letter", type: "item", first_seen_chapter: 1, description: "Addressed to Mira by name, dated two centuries before her birth." },
  { id: 7, canonical_name: "Tidelight", type: "concept", first_seen_chapter: 3, description: "The shell-coloured light that rises from beneath the glass." },
  { id: 8, canonical_name: "Captain Oren Hale", type: "character", first_seen_chapter: 12, description: "A harbour pilot who swears he has seen the city from above." },
  { id: 9, canonical_name: "The Bell Tower", type: "location", first_seen_chapter: 9, description: "Its bells mark each low tide; no one has climbed it in living memory." },
  { id: 10, canonical_name: "Archive Key", type: "item", first_seen_chapter: 18, description: "A key cut from the same glass as the shore." },
  { id: 11, canonical_name: "The Cartographers' Guild", type: "organization", first_seen_chapter: 15, description: "Mapmakers who insist their maps describe the future." },
  { id: 12, canonical_name: "Borrowed Names", type: "concept", first_seen_chapter: 7, description: "What the city takes from those who stay past the eleventh minute." },
];

export function entityProfile(id) {
  const e = entities.find(x => x.id === id) || entities[0];
  return {
    ...e, aliases: id === 1 ? ["the girl from Saltmere", "Vale"] : [], linked_personas: [],
    rendered_md: `**${e.canonical_name}** ${e.description} [Chunk 3, Chapter 1]\n\nFirst encountered on the glass shore before dawn, ${e.canonical_name.split(" ")[0]} carries a letter that seems to know more than it should. [Chunk 7, Chapter 2]\n\n## What we know\n\n- Arrived an hour before first light.\n- Was warned that the door stays open for eleven minutes.\n- Chose to go in.`,
    facts: [
      { id: 1, chapter: 1, fact_type: "event", content: "Arrived at the glass shore before dawn carrying an old letter." },
      { id: 2, chapter: 2, fact_type: "relationship", content: "Met the Archivist, who seemed to recognise her." },
      { id: 3, chapter: 3, fact_type: "trait", content: "Decides quickly once a door is open." },
    ],
  };
}

export const relationships = [
  { id: 1, source_id: 1, target_id: 2, source_name: "Mira Vale", target_name: "The Archivist", source_type: "character", target_type: "character", relation_type: "guided by", chapter: 1, content: "The Archivist explains the eleven minutes." },
  { id: 2, source_id: 1, target_id: 6, source_name: "Mira Vale", target_name: "The Unsent Letter", source_type: "character", target_type: "item", relation_type: "carries", chapter: 1, content: "Addressed to her by name." },
  { id: 3, source_id: 1, target_id: 3, source_name: "Mira Vale", target_name: "The Glass Shore", source_type: "character", target_type: "location", relation_type: "enters", chapter: 1, content: "Walks out onto the glass at low water." },
];

export const timeline = [
  { chapter: 1, content: "Reaches the glass shore; meets the Archivist." },
  { chapter: 2, content: "Learns the door opens for eleven minutes at first light." },
  { chapter: 3, content: "Enters the drowned city as the tide returns." },
];

/* ---------- activity / jobs ---------- */
export const activity = [
  { source: "job", id: 501, kind: "translate", status: "running", novel_id: 7, cancelable: true, progress: { done: 12, total: 40 }, created_at: iso(20 * 60e3), updated_at: iso(30e3), stage: "Translating chapter 617", execution_backend: "openai_codex" },
  { source: "job", id: 502, kind: "codex_build", status: "running", novel_id: 1, cancelable: true, progress: { step: 3, steps: 7, stage: "Extracting entities" }, created_at: iso(8 * 60e3), updated_at: iso(12e3) },
  { source: "tts", id: 77, kind: "tts", status: "queued", novel_id: 4, cancelable: true, progress: { done: 0, total: 12 }, created_at: iso(2 * 60e3), updated_at: iso(60e3) },
  { source: "job", id: 480, kind: "scrape", status: "done", novel_id: 2, cancelable: false, progress: { scraped: 3 }, created_at: iso(5 * 3600e3), updated_at: iso(4.9 * 3600e3) },
  { source: "import", id: 31, kind: "import", status: "committed", novel_id: 4, cancelable: false, created_at: iso(DAY), updated_at: iso(DAY - 600e3), filename: "letters-from-the-north.epub" },
  { source: "job", id: 470, kind: "codex_illustrate", status: "failed", novel_id: 10, cancelable: false, error: "Image provider unavailable — waiting before retrying", created_at: iso(2 * DAY), updated_at: iso(2 * DAY - 300e3), attempts: 3, max_attempts: 3 },
];

export const home = {
  continue_reading: [1, 7, 2, 10, 4].map(id => {
    const n = novelSummary(BOOKS.find(b => b.id === id));
    return { ...n, pct_read: Math.round((n.max_chapter_read / n.max_chapter) * 100), resume_chapter_title: TITLES[(n.last_chapter || 1) % TITLES.length] };
  }),
  updated_in_library: [7, 2].map(id => ({ ...novelSummary(BOOKS.find(b => b.id === id)) })),
  newest: SHARED.map(s => ({ id: s.id, title: s.title, author: s.author, cover_url: coverUrl(s.id), chapter_count: s.chapters, has_audio: s.audio, has_codex: s.codex })),
  recent_imports: [],
};

export const discover = [
  ...SHARED.map(s => ({ id: s.id, title: s.title, author: s.author, cover_url: coverUrl(s.id), chapter_count: s.chapters, has_codex: s.codex, has_audio: s.audio, translation_type: s.tt, owner_username: "archivist" })),
  ...novels.slice(0, 8).map(n => ({ ...n, has_codex: n.codex_enabled, has_audio: n.audio_chapters > 0, owner_username: "nishant" })),
];

export const voices = { voices: [
  { id: "dan", name: "Dan", ready: true, language: "en", gender: "male", accent: "US" },
  { id: "mira", name: "Mira", ready: true, language: "en", gender: "female", accent: "UK" },
  { id: "orson", name: "Orson", ready: true, language: "en", gender: "male", accent: "UK" },
], default: "dan" };

export const users = [
  { id: 1, username: "nishant", display_name: "Nishant", email: "reader@example.test", role: "admin", status: "active", email_verified: true, avatar_url: null, quota_overrides: {}, ai_backend_policy: { openai_codex_enabled: true, default_backend: "openai_codex", policy_version: 3 }, usage: { translated_chapters: 212, ocr_pages: 40, codex_builds: 6, tts_chapters: 90 }, limits: { translated_chapters: 1000, ocr_pages: 500, codex_builds: 20, tts_chapters: 300 } },
  { id: 2, username: "ari", display_name: "Ari", email: "ari@example.test", role: "user", status: "active", email_verified: true, avatar_url: null, quota_overrides: {}, ai_backend_policy: {}, usage: { translated_chapters: 34, ocr_pages: 0, codex_builds: 1, tts_chapters: 12 }, limits: { translated_chapters: 300, ocr_pages: 200, codex_builds: 5, tts_chapters: 100 } },
  { id: 3, username: "sol", display_name: "Sol", email: "sol@example.test", role: "user", status: "suspended", email_verified: false, avatar_url: null, quota_overrides: { ocr_pages: 50 }, ai_backend_policy: {}, usage: { translated_chapters: 3, ocr_pages: 50, codex_builds: 0, tts_chapters: 0 }, limits: { translated_chapters: 300, ocr_pages: 50, codex_builds: 5, tts_chapters: 100 } },
];

/* ---------- router ---------- */
export function respond(method, path, query) {
  const novelMatch = path.match(/^\/api\/novels\/(\d+)(\/.*)?$/);
  if (path === "/api/auth/me") return user;
  if (path === "/api/auth/providers") return { providers: ["google", "discord"] };
  if (path === "/api/auth/links") return { linked: ["google"], has_password: true };
  if (path === "/api/auth/login" || path === "/api/auth/register") return user;
  if (path === "/api/me/usage") return { unlimited: false, usage: { translated_chapters: 212, ocr_pages: 40, codex_builds: 6, tts_chapters: 90 }, limits: { translated_chapters: 1000, ocr_pages: 500, codex_builds: 20, tts_chapters: 300 } };
  if (path === "/api/home") return home;
  if (path === "/api/activity") return { jobs: query.get("status") === "active" ? activity.filter(j => j.cancelable) : activity };
  if (path === "/api/novels" && method === "GET") return novels;
  if (path === "/api/discover") return { items: discover, total: discover.length, offset: 0, limit: 60 };
  if (path === "/api/adapters") return [{ name: "royalroad", label: "Royal Road", default_language: "en", start_url_hint: "Paste the novel's main page." }, { name: "global-novelpia", label: "Novelpia Global", default_language: "en" }];
  if (path === "/api/tts/voices") return voices;
  if (path === "/api/jobs") return { jobs: activity.filter(j => j.source === "job").map(j => ({ ...j })) };
  if (path === "/api/import/jobs") return [
    { id: 31, status: "committed", filename: "letters-from-the-north.epub", detected_meta: { title: "Letters from the North" }, novel_id: 4 },
    { id: 32, status: "awaiting_review", filename: "moonlit-archive-vol2.epub", detected_meta: { title: "Moonlit Archive", series: "Moonlit Archive", series_index: 2 } },
  ];
  const importJob = path.match(/^\/api\/import\/jobs\/(\d+)$/);
  if (importJob) {
    const segments = Array.from({ length: 14 }, (_, i) => ({ id: `s${i}`, title: i === 0 ? "Prologue: The Night Stacks" : `Chapter ${i}: ${TITLES[i % TITLES.length]}`, kind: i === 0 ? "frontmatter" : "chapter", number: i === 0 ? null : i, include: true, part_label: "Volume 2", block_range: [i * 40, i * 40 + 39], word_count: 2800 + i * 37, first_line: "The library opened only under a full moon, and it was always overdue." }));
    return { id: Number(importJob[1]), status: "awaiting_review", filename: "moonlit-archive-vol2.epub", stage: null,
      detected_meta: { title: "Moonlit Archive", author: "Sable Ren", series: "Moonlit Archive", series_index: 2, volume_label: "Volume 2", language: "en", description: "The second volume of the night library." },
      stats: { segments: 14, images: 6, quality: { score: 91, factors: [{ ok: true, label: "Chapter numbering", detail: "continuous" }] } },
      plan: { version: 1, segments }, options: {} };
  }
  if (path === "/api/settings/novelpia-cookies") return { configured: false, usable: false, updated_at: null, cookies: [] };
  if (path.startsWith("/api/users/")) return {
    username: "nishant", display_name: "Nishant", role: "admin", bio: user.bio, avatar_url: null, created_at: user.created_at, is_self: true,
    stats: { library_count: 10, reading_count: 5, completed_count: 2, chapters_read: 1388 },
    currently_reading: home.continue_reading, recently_finished: [3, 8].map(id => novelSummary(BOOKS.find(b => b.id === id))), published: novels.slice(0, 4),
  };
  if (path === "/api/admin/users") return users;
  if (path === "/api/admin/usage") return { totals: { translated_chapters: 249, ocr_pages: 90, codex_builds: 7, active_users: 2 }, user_count: 3, novel_count: 14, top_spenders: users.map(u => ({ ...u, ...u.usage })), months: [0, 1, 2, 3].map(i => ({ period: new Date(now - i * 31 * DAY).toISOString(), translated_chapters: 240 - i * 40, ocr_pages: 90 - i * 10, codex_builds: 7 - i })) };
  if (path === "/api/admin/novels") return novels.map(n => ({ ...n, owner_username: "nishant" }));
  if (path.startsWith("/api/admin/global")) return novels.filter(n => n.visibility === "global").map(n => ({ ...n, source_count: 1, last_scraped_at: iso(DAY), has_raw: true, untranslated: 4 }));
  if (path.startsWith("/api/admin/ai/")) return { enabled: true, available: true, worker: { status: "idle", version: "0.52.0", plugin_version: "1.1.2", contract_version: "3" }, queue: { queued: 1, running: 1, waiting_provider: 0 }, last_success_at: iso(3600e3), recent_failures: [] };

  if (novelMatch) {
    const id = Number(novelMatch[1]);
    const rest = novelMatch[2] || "";
    const detail = novelDetail(id);
    if (!rest) return detail;
    if (rest === "/chapters") return chapterList(id);
    const ch = rest.match(/^\/chapter\/([\d.]+)$/);
    if (ch) return chapter(id, Number(ch[1]));
    if (rest === "/progress") return detail ? detail.progress : {};
    if (rest === "/bookmarks") return id === 1 ? [{ id: 1, chapter: 117, note: "The door opens" }, { id: 2, chapter: 42, note: null }] : [];
    if (rest === "/stats") return { entities: entities.length, facts: 60, effective_ceiling: Number(query.get("ceiling")) || 118, ceiling_clamped: false, built_chapter_count: 118, built_through_chapter: 118, entities_revealed: entities.length, ceiling_title: "Glasswork" };
    if (rest === "/entities") {
      const type = query.get("type"); const q = (query.get("q") || "").toLowerCase();
      return entities.filter(e => (!type || e.type === type) && (!q || e.canonical_name.toLowerCase().includes(q)));
    }
    const ent = rest.match(/^\/entity\/(\d+)(\/.*)?$/);
    if (ent) {
      if (!ent[2]) return entityProfile(Number(ent[1]));
      if (ent[2] === "/relationships") return relationships;
      if (ent[2] === "/timeline") return timeline;
      if (ent[2] === "/identities") return [];
    }
    if (rest === "/ask") return { answer: "Mira reaches the glass shore before dawn and meets the Archivist, who explains that the door beneath the glass opens for only eleven minutes at first light [Chunk 3, Chapter 1]. She chooses to go in as the tide returns [Chunk 9, Chapter 3].", citations: [{ kind: "chunk", id: 3, chapter: 1, snippet: "The tide turns at first light. When it does, the door opens for eleven minutes." }, { kind: "chunk", id: 9, chapter: 3, snippet: "Behind her the tide came in, soft as a turning page." }], effective_ceiling: 118, ceiling_clamped: false };
    if (rest === "/recap") return { answer: "Mira follows an impossible letter to the glass shore, where a drowned city appears at low water. The Archivist warns her of the eleven-minute door; Mira goes in [Chunk 9, Chapter 3].", citations: [{ kind: "chunk", id: 9, chapter: 3, snippet: "Behind her the tide came in, soft as a turning page." }] };
    if (rest === "/audio/coverage") return { prose_chapters: detail ? detail.chapter_count : 0, chapters: [1, 2, 3, 4, 5].map(c => ({ chapter: c, voices: ["dan"] })), voices: [{ voice_id: "dan", have: 60 }] };
    if (rest.startsWith("/audiobook/status")) return { active: false };
    if (/\/chapter\/[\d.]+\/audio\/status$/.test(rest)) return { cached: false, available_voices: ["dan"] };
    if (rest === "/health") return { codex: { entities: 12, missing: false, stale: true, coverage_chapter: 118 }, untranslated_raw_chapters: 4, total_chapters: detail ? detail.chapter_count : 0, book_max_chapter: detail ? detail.max_chapter : 0, audio: { prose_chapters: 240, missing: 180, voices: [{ voice_id: "dan", have: 60 }] }, source_last_scraped: iso(DAY), recent_errors: [] };
    if (rest === "/glossary") return [{ id: 1, source_term: "林轩", translation: "Lin Xuan", term_type: "name", locked: true }, { id: 2, source_term: "天剑宗", translation: "Heavenly Sword Sect", term_type: "place", locked: false }];
    if (rest === "/contributions") return [];
    if (rest === "/tag-suggestions") return [];
    if (rest === "/illustrations") return { can_generate: true, active_job: null };
    if (/\/chapters\/[\d.]+\/illustrations$/.test(rest)) return { items: [], can_generate: true, active_job: null };
    if (rest.startsWith("/cost-estimate")) return { estimated_units: 12, quota_kind: "translated_chapters", unlimited: false, remaining: 788, limit: 1000, allowed: true, spend_allowed: true };
    if (rest === "/meta") return { title: detail && detail.title };
    return {};
  }
  return {};
}
