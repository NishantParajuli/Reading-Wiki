/* ============================================================
   Codex showcase fixtures (synthetic) — extends fixtures.mjs for the Codex,
   Ask and chapter-illustration surfaces:
     · entities/stats honour the requested ceiling (so lowering then raising
       the boundary makes entries surface),
     · a longer cited answer + recap, identity reveals, more relationships,
     · chapter illustrations with synthetic SVG plates (scenes, reference
       sheets, one legacy style) served from /api/mock-art/*.svg.
   Wire into shoot.mjs by consulting respondCodex() before respond():
     const art = codexArt(url.pathname); if (art) → fulfill image/svg+xml
     const hit = respondCodex(method, url.pathname, url.searchParams);
     if (hit !== undefined) → fulfill JSON(hit)
   Everything here is explicitly synthetic test data.
   ============================================================ */
import { entities as baseEntities, entityProfile as baseProfile } from "./fixtures.mjs";

const NOVEL = /^\/api\/novels\/1(\/.*)?$/;

export const codexEntities = baseEntities;

function ceilingOf(query, fallback = 118) {
  const value = Number(query.get("ceiling"));
  return Number.isFinite(value) && value > 0 ? Math.min(value, 118) : fallback;
}

const RELATIONSHIPS = [
  { id: 1, source_id: 1, target_id: 2, source_name: "Mira Vale", target_name: "The Archivist", source_type: "character", target_type: "character", relation_type: "guided by", chapter: 1, content: "The Archivist explains the eleven minutes." },
  { id: 2, source_id: 1, target_id: 6, source_name: "Mira Vale", target_name: "The Unsent Letter", source_type: "character", target_type: "item", relation_type: "carries", chapter: 1, content: "Addressed to her by name." },
  { id: 3, source_id: 1, target_id: 3, source_name: "Mira Vale", target_name: "The Glass Shore", source_type: "character", target_type: "location", relation_type: "enters", chapter: 1, content: "Walks out onto the glass at low water." },
  { id: 4, source_id: 4, target_id: 1, source_name: "Saltmere", target_name: "Mira Vale", source_type: "location", target_type: "character", relation_type: "home of", chapter: 2, content: "The village she left before dawn." },
  { id: 5, source_id: 1, target_id: 5, source_name: "Mira Vale", target_name: "The Order of Low Water", source_type: "character", target_type: "faction", relation_type: "watched by", chapter: 6, content: "They record every time she crosses." },
  { id: 6, source_id: 1, target_id: 7, source_name: "Mira Vale", target_name: "Tidelight", source_type: "character", target_type: "concept", relation_type: "drawn to", chapter: 3, content: "Follows the shell-coloured light downward." },
];

const ANSWER = [
  "Mira reaches the glass shore an hour before dawn, carrying a letter addressed to her by name and dated two centuries before her birth [Chunk 3, Chapter 1]. There she meets **the Archivist**, a small woman in an oversized coat who seems to recognise her.",
  "The Archivist explains the one rule that matters: when the tide turns at first light, the door beneath the glass opens for only eleven minutes [Chunk 6, Chapter 1]. Whoever is inside when it closes stays until the next low water — sometimes for a year, sometimes longer.",
  "- She is warned that everyone comes out, but not always as themselves [Chunk 8, Chapter 2].\n- She chooses to go in anyway, just as the tide begins to return [Chunk 9, Chapter 3].",
].join("\n\n");

const CITATIONS = [
  { kind: "chunk", id: 3, chapter: 1, snippet: "It had been addressed to her by name, in a hand she did not recognise, and dated long before her grandmother was born." },
  { kind: "chunk", id: 6, chapter: 1, snippet: "The tide turns at first light. When it does, the door opens for eleven minutes." },
  { kind: "chunk", id: 8, chapter: 2, snippet: "“Everyone comes out,” she said. “The question is always who.”" },
  { kind: "chunk", id: 9, chapter: 3, snippet: "Behind her the tide came in, soft as a turning page." },
];

const art = (name) => `/api/mock-art/${name}.svg`;
const ILLUSTRATIONS = {
  can_generate: true,
  active_job: null,
  items: [
    { id: "scene-dawn", kind: "scene", style: "luminous", title: "The glass shore before dawn", caption: "Mira steps onto the clouded glass while the sea is still a rumour.", placement: { position: "after", anchor: "caught the last of the moonlight like a held breath" }, image_url: art("scene-dawn"), design_notes: "Cool moonlight from the upper left; the sunken city glows faintly beneath the glass." },
    { id: "scene-lantern", kind: "scene", style: "luminous", title: "The Archivist's lantern", caption: "A lantern that gives no heat, held by someone who seems to know her.", placement: { position: "after", anchor: "a word in a language one almost remembers" }, image_url: art("scene-lantern") },
    { id: "ref-mira", kind: "reference", style: "luminous", title: "Mira Vale", caption: "Travel coat, salt-stained boots, the letter always in her left pocket.", image_url: art("ref-mira") },
    { id: "ref-archivist", kind: "reference", style: "luminous", title: "The Archivist", caption: "Oversized coat, cold lantern, eyes that have read everything.", image_url: art("ref-archivist") },
    { id: "old-celestial", kind: "scene", style: "celestial", title: "Moon over Saltmere", caption: "An earlier style, kept for reference.", image_url: art("old-celestial") },
  ],
};

/* JSON responses; undefined = not handled here. */
export function respondCodex(method, path, query) {
  const m = path.match(NOVEL);
  if (!m) return undefined;
  const rest = m[1] || "";
  if (rest === "/stats") {
    const ceiling = ceilingOf(query);
    const shown = codexEntities.filter(e => e.first_seen_chapter <= ceiling).length;
    return {
      ceiling, effective_ceiling: ceiling, requested_ceiling: ceiling, ceiling_clamped: false,
      entities_revealed: shown, facts_known: Math.round(shown * 4.5), relationships_known: RELATIONSHIPS.filter(r => r.chapter <= ceiling).length,
      built_chapter_count: 118, built_through_chapter: 118, max_chapter: 240, pct_read: Math.round(ceiling / 240 * 100),
      ceiling_title: ceiling >= 118 ? "Glasswork" : ceiling >= 5 ? "A City Beneath" : "Arrival",
    };
  }
  if (rest === "/entities") {
    const ceiling = ceilingOf(query);
    const type = query.get("type");
    const q = (query.get("q") || "").toLowerCase();
    return codexEntities.filter(e => e.first_seen_chapter <= ceiling && (!type || e.type === type) && (!q || e.canonical_name.toLowerCase().includes(q)));
  }
  const ent = rest.match(/^\/entity\/(\d+)(\/.*)?$/);
  if (ent) {
    const id = Number(ent[1]);
    if (!ent[2]) return { ...baseProfile(id), facts: [...baseProfile(id).facts, { id: 4, chapter: 3, fact_type: "event", content: "Enters the drowned city as the tide returns." }, { id: 5, chapter: 6, fact_type: "status", content: "Is now recorded in the ledgers of the Order of Low Water." }] };
    if (ent[2] === "/relationships") return RELATIONSHIPS.filter(r => r.source_id === id || r.target_id === id);
    if (ent[2] === "/identities") return id === 2 ? [{ other_id: 11, other_name: "The Cartographers' Guild", note: "The Archivist is revealed to have founded the Cartographers' Guild under another name.", revealed_at_chapter: 64 }] : [];
    return undefined;
  }
  if (rest === "/ask" && method === "POST") return { answer: ANSWER, citations: CITATIONS, effective_ceiling: 118, ceiling_clamped: false };
  if (rest === "/recap" || rest.startsWith("/recap")) return { answer: "Mira follows an impossible letter to the glass shore, where a drowned city appears at low water [Chunk 3, Chapter 1]. The Archivist warns her about the eleven-minute door, and — as the tide turns — Mira goes in [Chunk 9, Chapter 3].\n\nThe Order of Low Water has begun to record her crossings.", citations: CITATIONS };
  if (/^\/chapters\/5\/illustrations$/.test(rest) && method === "GET") return ILLUSTRATIONS;
  return undefined;
}

/* ---------- synthetic plates (SVG) ---------- */
const scene = (body, w = 1200, h = 800) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${body}</svg>`;

function waves(y0, color, amp, count, opacity) {
  let d = `M0 ${y0}`;
  for (let i = 0; i <= count; i++) {
    const x = (1200 / count) * i;
    d += ` Q ${x - 1200 / count / 2} ${y0 + (i % 2 ? amp : -amp)} ${x} ${y0}`;
  }
  return `<path d="${d} L1200 800 L0 800 Z" fill="${color}" opacity="${opacity}"/>`;
}

const ART = {
  "scene-dawn": () => scene(`
    <defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0d1a3a"/><stop offset=".55" stop-color="#3b4f7a"/><stop offset=".78" stop-color="#e9b9a5"/><stop offset="1" stop-color="#f6dcc3"/></linearGradient>
      <radialGradient id="moon" cx=".72" cy=".2" r=".2"><stop offset="0" stop-color="#fffbe8"/><stop offset=".18" stop-color="#fff3c9" stop-opacity=".95"/><stop offset=".5" stop-color="#ffe9b0" stop-opacity=".22"/><stop offset="1" stop-color="#ffe9b0" stop-opacity="0"/></radialGradient>
      <linearGradient id="glass" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#b9d6e6"/><stop offset="1" stop-color="#4f7c95"/></linearGradient>
      <radialGradient id="glow" cx=".45" cy=".82" r=".35"><stop offset="0" stop-color="#ffd9f0" stop-opacity=".75"/><stop offset="1" stop-color="#ffd9f0" stop-opacity="0"/></radialGradient>
    </defs>
    <rect width="1200" height="800" fill="url(#sky)"/>
    <rect width="1200" height="800" fill="url(#moon)"/>
    ${Array.from({ length: 70 }, (_, i) => `<circle cx="${(i * 173) % 1200}" cy="${(i * 97) % 330}" r="${(i % 3) * 0.6 + 0.6}" fill="#fff" opacity="${0.25 + (i % 5) * 0.12}"/>`).join("")}
    <rect y="520" width="1200" height="280" fill="url(#glass)"/>
    <g opacity=".55" fill="#2b4f6a">
      <rect x="180" y="600" width="60" height="110"/><polygon points="170,600 210,560 250,600"/>
      <rect x="270" y="630" width="90" height="90"/><rect x="380" y="590" width="44" height="130"/><polygon points="372,590 402,540 432,590"/>
      <rect x="760" y="610" width="80" height="100"/><rect x="860" y="580" width="50" height="140"/><polygon points="850,580 885,530 920,580"/>
      <ellipse cx="560" cy="700" rx="80" ry="14"/><rect x="552" y="650" width="16" height="50"/>
    </g>
    <rect y="520" width="1200" height="280" fill="url(#glow)"/>
    ${[540, 575, 615, 660].map((y, i) => `<path d="M0 ${y} C 300 ${y - 8}, 900 ${y + 8}, 1200 ${y}" stroke="#eaf6ff" stroke-opacity="${0.35 - i * 0.06}" stroke-width="1.5" fill="none"/>`).join("")}
    <g transform="translate(585 470)"><path d="M0 50 C -6 20, -8 4, 0 0 C 8 4, 6 20, 0 50 Z" fill="#101a2e"/><circle cx="0" cy="-8" r="7" fill="#101a2e"/><path d="M-4 18 L-22 60 L22 60 L4 18 Z" fill="#141f36"/></g>
    <ellipse cx="590" cy="532" rx="42" ry="5" fill="#0e1830" opacity=".45"/>`),
  "scene-lantern": () => scene(`
    <defs>
      <linearGradient id="sky2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#070b1d"/><stop offset=".6" stop-color="#15294a"/><stop offset="1" stop-color="#23476a"/></linearGradient>
      <radialGradient id="lamp" cx=".56" cy=".5" r=".32"><stop offset="0" stop-color="#fff2c6"/><stop offset=".12" stop-color="#ffd98a" stop-opacity=".9"/><stop offset=".45" stop-color="#ffb35c" stop-opacity=".2"/><stop offset="1" stop-color="#ffb35c" stop-opacity="0"/></radialGradient>
      <radialGradient id="cool" cx=".2" cy=".15" r=".5"><stop offset="0" stop-color="#9fd8ff" stop-opacity=".35"/><stop offset="1" stop-color="#9fd8ff" stop-opacity="0"/></radialGradient>
    </defs>
    <rect width="1200" height="800" fill="url(#sky2)"/>
    <rect width="1200" height="800" fill="url(#cool)"/>
    ${waves(610, "#1c3b5c", 10, 12, 1)}${waves(650, "#16304d", 14, 9, 1)}${waves(705, "#0f233b", 12, 7, 1)}
    <rect width="1200" height="800" fill="url(#lamp)"/>
    <g transform="translate(610 330)">
      <path d="M-120 330 C -110 170, -70 60, 0 40 C 70 60, 110 170, 120 330 Z" fill="#241a2e"/>
      <circle cx="0" cy="10" r="38" fill="#2c2138"/>
      <path d="M-38 6 C -30 -34, 30 -34, 38 6 C 30 -8, -30 -8, -38 6 Z" fill="#3b2a44"/>
      <path d="M60 120 L118 150" stroke="#2c2138" stroke-width="16" stroke-linecap="round"/>
      <g transform="translate(130 150)"><line x1="0" y1="0" x2="0" y2="24" stroke="#c9a46a" stroke-width="3"/><rect x="-18" y="24" width="36" height="46" rx="8" fill="#ffe7a8"/><rect x="-18" y="24" width="36" height="46" rx="8" fill="none" stroke="#b98a45" stroke-width="3"/><circle cx="0" cy="47" r="10" fill="#fff8e0"/></g>
    </g>
    ${Array.from({ length: 14 }, (_, i) => `<circle cx="${80 + i * 80}" cy="${660 + (i % 3) * 22}" r="${4 + (i % 2) * 2}" fill="#ffd98a" opacity="${0.35 + (i % 4) * 0.12}"/>`).join("")}`),
  "ref-mira": () => refSheet("Mira Vale", "#2f6f86", "#e9c9a0", "#3b4d6e"),
  "ref-archivist": () => refSheet("The Archivist", "#6d4f7c", "#e2d3c1", "#4a3a2e"),
  "old-celestial": () => scene(`
    <defs><radialGradient id="c" cx=".5" cy=".4" r=".7"><stop offset="0" stop-color="#2d2a6e"/><stop offset="1" stop-color="#08081c"/></radialGradient></defs>
    <rect width="1200" height="800" fill="url(#c)"/>
    ${Array.from({ length: 160 }, (_, i) => `<circle cx="${(i * 131) % 1200}" cy="${(i * 71) % 800}" r="${(i % 4) * 0.5 + 0.5}" fill="#fff" opacity="${0.3 + (i % 5) * 0.12}"/>`).join("")}
    <circle cx="600" cy="300" r="90" fill="#f6f0d8"/><circle cx="632" cy="282" r="86" fill="#2d2a6e"/>`),
};

function refSheet(name, coat, skin, hair) {
  const pose = (x, flip) => `<g transform="translate(${x} 150)${flip ? " scale(-1 1)" : ""}">
      <circle cx="0" cy="40" r="34" fill="${skin}"/><path d="M-36 34 C -34 -6, 34 -6, 36 34 C 24 16, -24 16, -36 34 Z" fill="${hair}"/>
      <path d="M-58 100 C -50 80, 50 80, 58 100 L 70 380 L -70 380 Z" fill="${coat}"/>
      <rect x="-40" y="380" width="30" height="150" rx="10" fill="#2a2f3f"/><rect x="10" y="380" width="30" height="150" rx="10" fill="#2a2f3f"/>
      <rect x="-46" y="520" width="40" height="18" rx="6" fill="#3a2d24"/><rect x="6" y="520" width="40" height="18" rx="6" fill="#3a2d24"/></g>`;
  return scene(`
    <rect width="1200" height="800" fill="#f3ede2"/>
    <rect x="30" y="30" width="1140" height="740" fill="none" stroke="#cbbfa9" stroke-width="2"/>
    ${[260, 520, 780].map((x, i) => pose(x, i === 2)).join("")}
    ${[260, 520, 780].map((x, i) => `<text x="${x}" y="730" text-anchor="middle" font-family="Georgia, serif" font-size="22" fill="#6b604e">${["front", "three-quarter", "back"][i]}</text>`).join("")}
    <g transform="translate(980 170)">${[coat, skin, hair, "#2a2f3f", "#3a2d24"].map((c, i) => `<rect x="0" y="${i * 70}" width="120" height="52" rx="10" fill="${c}"/>`).join("")}</g>
    <text x="70" y="96" font-family="Georgia, serif" font-style="italic" font-size="40" fill="#3f372c">${name}</text>
    <text x="70" y="130" font-family="Helvetica, Arial, sans-serif" font-size="16" letter-spacing="4" fill="#8b806c">CHARACTER REFERENCE · SYNTHETIC FIXTURE</text>`);
}

/* SVG body for /api/mock-art/<name>.svg; null when not an art path. */
export function codexArt(path) {
  const m = path.match(/^\/api\/mock-art\/([a-z-]+)\.svg$/);
  if (!m || !ART[m[1]]) return null;
  return ART[m[1]]();
}
