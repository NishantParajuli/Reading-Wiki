/* Import job vocabulary shared by the wizard, the tideline and the history list. */
export const IMPORT_KINDS = ["chapter", "frontmatter", "interlude", "backmatter"];
export const IMPORT_KIND_LABEL = { chapter: "Chapter", frontmatter: "Front matter", interlude: "Interlude", backmatter: "Back matter" };
export const IMPORT_BUSY = ["receiving", "uploaded", "parsing", "segmenting", "committing", "commit_running",
  "ocr_pending", "ocr_running", "ocr_paused"];
export const IMPORT_STATUS_LABEL = {
  receiving: "Receiving…", uploaded: "Queued…", parsing: "Parsing…", segmenting: "Segmenting…",
  awaiting_ocr_confirm: "Scanned — needs OCR", ocr_pending: "OCR queued…", ocr_running: "Reading pages…",
  ocr_paused: "OCR paused (budget)", awaiting_review: "Ready to review",
  committing: "Committing…", commit_running: "Committing…",
  committed: "Committed", failed: "Failed", canceled: "Canceled",
};
export const OCR_STATUSES = ["awaiting_ocr_confirm", "ocr_pending", "ocr_running", "ocr_paused"];

/* Where a job sits in the wizard: 0 upload, 1 parse, 2 ocr, 3 review, 4 commit(ted). */
export function stepOf(job) {
  if (!job) return 0;
  const s = job.status;
  if (["receiving", "uploaded", "parsing", "segmenting"].includes(s)) return 1;
  if (OCR_STATUSES.includes(s)) return 2;
  if (s === "awaiting_review") return 3;
  if (["committing", "commit_running", "committed"].includes(s)) return 4;
  return 1;
}

/* The tone of a status dot: the server is working (pulses), waiting on the
   reader, paused, finished, failed or idle. */
export function importTone(status) {
  if (status === "committed") return "done";
  if (status === "failed") return "failed";
  if (status === "canceled") return "idle";
  if (status === "ocr_paused") return "paused";
  if (status === "awaiting_review" || status === "awaiting_ocr_confirm") return "attention";
  if (IMPORT_BUSY.includes(status)) return "working";
  return "idle";
}

export function importTitle(job) {
  return (job && job.detected_meta && job.detected_meta.title) || (job && job.filename) || (job ? `Import ${job.id}` : "");
}
