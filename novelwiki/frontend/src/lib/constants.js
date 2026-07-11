/* Shared vocabulary: shelves, status tags, translation types, job labels.
   Must mirror the backend STATUS_TAG_RADIO_GROUPS / GENRE_TAGS in api/routes.py. */

export const SHELF_LABELS = { to_read: "To read", reading: "Reading", completed: "Completed" };
export const SHELF_ORDER = ["reading", "to_read", "completed"];

export const STATUS_TAG_RADIO_GROUPS = [
  { id: "status", label: "Status", tags: ["ongoing", "finished", "hiatus"] },
  { id: "translation", label: "Translation", tags: ["translation_ongoing", "translation_completed"] },
];
export const GENRE_TAGS = ["action", "adventure", "romance", "fantasy", "sci_fi", "comedy", "drama", "horror", "mystery", "slice_of_life"];
export const STATUS_TAG_LABELS = {
  ongoing: "Ongoing", finished: "Finished", hiatus: "Hiatus",
  translation_ongoing: "Translation ongoing", translation_completed: "Translation complete",
  action: "Action", adventure: "Adventure", romance: "Romance", fantasy: "Fantasy",
  sci_fi: "Sci-fi", comedy: "Comedy", drama: "Drama", horror: "Horror",
  mystery: "Mystery", slice_of_life: "Slice of life",
};
export const STATUS_TAG_ORDER = [
  ...STATUS_TAG_RADIO_GROUPS.flatMap(g => g.tags), ...GENRE_TAGS,
];
export const TRANSLATION_TYPE_LABELS = { translated: "Translated", raws: "Raws", "raws+translated": "Raws + Translated" };

export const VIS_LABELS = { global: "Global", public: "Public", private: "Private" };

export const TYPE_ICON = { character: "user", location: "mapPin", faction: "users", item: "gem", concept: "spark", organization: "users" };
export const TYPE_LABEL = { character: "Character", location: "Location", faction: "Faction", item: "Item", concept: "Concept", organization: "Org" };

export const PROVENANCE_LABELS = {
  scraped: { label: "Scraped", title: "Chapters pulled from a web source" },
  imported: { label: "Imported", title: "Ingested from an uploaded EPUB/PDF" },
  ocr: { label: "OCR'd", title: "Text recovered from a scanned document" },
  translated: { label: "Translated", title: "Machine-translated from a raw source" },
  user_edited: { label: "Edited", title: "The text has reader/owner edits" },
  owner_approved: { label: "Owner-approved", title: "A contributed translation was accepted" },
};
export const PROVENANCE_ORDER = ["scraped", "imported", "ocr", "translated", "user_edited", "owner_approved"];

// Activity / job vocabulary (shared by Home strip, Jobs page, novel Manage tab).
export const ACT_KIND_LABEL = {
  scrape: "Scrape", codex_build: "Codex build", translate: "Translation",
  agy_smoke: "AGY smoke", import: "Import", tts: "Narration",
};
export const ACT_KIND_ICON = {
  scrape: "spider", codex_build: "brain", translate: "globe",
  agy_smoke: "cpu", import: "upload", tts: "headphones",
};
// status → chip tone
export const ACT_STATUS_TONE = {
  queued: "neutral", running: "accent", generating: "accent",
  parsing: "accent", segmenting: "accent", committing: "accent", commit_running: "accent",
  receiving: "accent", ocr_pending: "accent", ocr_running: "accent",
  done: "ok", committed: "ok",
  waiting_provider: "warn", awaiting_review: "warn", awaiting_ocr_confirm: "warn", ocr_paused: "warn",
  failed: "danger", canceled: "neutral", uploaded: "accent",
};

export function activityProgress(job) {
  const p = job.progress || {};
  if (job.source === "tts") {
    if (p.total != null) return `${p.done || 0}/${p.total} narrated${p.current_chapter != null ? ` — ch. ${p.current_chapter}` : ""}`;
    return job.stage || "narrating…";
  }
  if (job.source === "import") return job.stage || job.status;
  if (job.kind === "translate" && p.total != null) {
    let s = `${p.done || 0}/${p.total} translated`;
    if (p.failed) s += `, ${p.failed} failed`;
    if (p.stopped_reason === "quota") s += " — stopped (quota)";
    return s;
  }
  if (job.kind === "codex_build" && p.steps != null) return `step ${p.step || 0}/${p.steps}${p.stage ? ` — ${p.stage}` : ""}`;
  if (job.kind === "scrape" && p.scraped != null) return `${p.scraped} chapters scraped`;
  return job.stage || "";
}

export function activityFraction(job) {
  const p = job.progress || {};
  if (p.total > 0 && p.done != null) return Math.min(1, p.done / p.total);
  if (p.steps > 0 && p.step != null) return Math.min(1, p.step / p.steps);
  return null;
}
