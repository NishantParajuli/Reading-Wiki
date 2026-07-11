import { expect, test } from "@playwright/test";

const user = {
  id: 1, username: "reader", display_name: "Reader", role: "admin", status: "active",
  email_verified: true, prefs: {}, quota_translated_chapters: 100, quota_ocr_pages: 100,
  quota_codex_builds: 100, quota_tts_chapters: 100,
  quota_overrides: {}, ai_backend_policy: {},
  usage: { translated_chapters: 0, ocr_pages: 0, codex_builds: 0, tts_chapters: 0 },
  limits: { translated_chapters: 100, ocr_pages: 100, codex_builds: 100, tts_chapters: 100 },
  email: "reader@example.test",
};
const novel = {
  id: 7, title: "The Glass Tide", description: "A test story", visibility: "private",
  is_owner: true, can_edit: true, codex_enabled: true, chapter_count: 2,
  min_chapter: 1, max_chapter: 2, status_tags: [], sources: [],
  progress: { last_chapter: 1, scroll_pct: 0.35, max_chapter_read: 1 },
};
const chapter = {
  number: 1, title: "Arrival", content: "The tide reached the glass shore.",
  rich_html: null, prev: null, next: 2, next_title: "Undertow", next_is_raw: false,
  overlay: null, overlay_conflict: false, is_raw: false,
};

async function mockApi(page, { signedIn = true } = {}) {
  await page.route("http://127.0.0.1:4173/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let status = 200;
    let body = { status: "success" };
    if (path === "/api/auth/me") {
      if (!signedIn) { status = 401; body = { detail: "Not authenticated." }; }
      else body = user;
    } else if (path === "/api/auth/providers") body = { providers: [] };
    else if (path === "/api/auth/login" || path === "/api/auth/register") body = user;
    else if (path === "/api/home") body = { continue_reading: [novel], updated_in_library: [], newest: [], recent_imports: [] };
    else if (path === "/api/activity") body = [];
    else if (path === "/api/novels") body = [novel];
    else if (path === "/api/discover") body = { items: [novel], total: 1, offset: 0, limit: 60 };
    else if (path === "/api/novels/7") body = novel;
    else if (path === "/api/novels/7/chapters") body = [{ number: 1, title: "Arrival" }, { number: 2, title: "Undertow" }];
    else if (path === "/api/novels/7/chapter/1") body = chapter;
    else if (path === "/api/novels/7/progress") body = novel.progress;
    else if (path === "/api/novels/7/bookmarks") body = [];
    else if (path === "/api/adapters") body = [];
    else if (path === "/api/jobs") body = { jobs: [] };
    else if (path === "/api/novels/7/health") body = {
      codex: { entities: 0, missing: true, stale: false },
      untranslated_raw_chapters: 0, total_chapters: 2, recent_errors: [],
    };
    else if (path === "/api/novels/7/glossary") body = [];
    else if (path === "/api/novels/7/contributions") body = [];
    else if (path === "/api/novels/7/tag-suggestions") body = [];
    else if (path === "/api/novels/7/stats") body = { entities: 1, facts: 1, effective_ceiling: 1, ceiling_clamped: false };
    else if (path === "/api/novels/7/entities") body = [{ id: 1, canonical_name: "Mira", type: "character", first_seen_chapter: 1 }];
    else if (path === "/api/novels/7/ask") body = { answer: "Mira arrives.", citations: [], evidence_ids: [], requested_ceiling: 1, allowed_ceiling: 1, effective_ceiling: 1, ceiling_clamped: false };
    else if (path === "/api/novels/7/recap") body = { answer: "Previously, Mira arrived.", citations: [] };
    else if (path === "/api/import/jobs") body = [];
    else if (path === "/api/tts/voices") body = { voices: [{ id: "v1", name: "Test voice", ready: true }], default: "v1" };
    else if (path === "/api/novels/7/audio/coverage") body = [];
    else if (path === "/api/admin/users") body = [user];
    else if (path === "/api/admin/ai/agy/health") body = { enabled: false, queue: {} };
    await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  });
}

test("register/login gate and session recovery surface", async ({ page }) => {
  await mockApi(page, { signedIn: false });
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await page.getByLabel(/email or username/i).fill("reader");
  await page.getByText("Password", { exact: true }).locator("..").locator("input").fill("secret-password");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByText("The Glass Tide").first()).toBeVisible();
});

test("library and discover preserve add/navigation surfaces", async ({ page }) => {
  await mockApi(page);
  await page.goto("/library");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await page.goto("/discover");
  await expect(page.getByRole("heading", { name: "Discover" })).toBeVisible();
  await expect(page.getByText("The Glass Tide").first()).toBeVisible();
});

test("reader restores chapter, bookmarks, settings and navigation", async ({ page }) => {
  await mockApi(page);
  await page.goto("/n/7/read/1");
  await expect(page.getByRole("heading", { name: "Arrival" })).toBeVisible();
  await expect(page.getByText("The tide reached the glass shore.")).toBeVisible();
  await page.getByRole("button", { name: "Bookmark" }).click();
  await page.getByRole("button", { name: "Reading settings" }).click();
  await expect(page.getByLabel("Font size")).toBeVisible();
});

test("translation conflict tooling remains reachable", async ({ page }) => {
  await mockApi(page);
  await page.goto("/n/7/read/1");
  await page.getByRole("button", { name: /edit translation/i }).click();
  await expect(page.getByPlaceholder("Chapter translation…")).toBeVisible();
});

test("import upload and review surface is operational", async ({ page }) => {
  await mockApi(page);
  await page.goto("/import");
  await expect(page.getByRole("heading", { name: "Import a book" })).toBeVisible();
  await expect(page.getByText(/Drop an EPUB or PDF/i)).toBeVisible();
  await expect(page.getByText("Recent imports")).toBeVisible();
});

test("unified activity exposes schedule/cancel state", async ({ page }) => {
  await mockApi(page);
  await page.goto("/jobs");
  await expect(page.getByRole("heading", { name: "Jobs" })).toBeVisible();
  await expect(page.getByText("No active jobs")).toBeVisible();
});

test("codex ceiling and cached ask remain usable", async ({ page }) => {
  await mockApi(page);
  await page.goto("/n/7/ask");
  await expect(page.getByRole("heading", { name: "Ask the Codex" })).toBeVisible();
  await page.getByRole("textbox").fill("Who arrives?");
  await page.getByRole("button", { name: /ask/i }).click();
  await expect(page.getByText("Mira arrives.")).toBeVisible();
});

test("cached narration controls render with mocked voice service", async ({ page }) => {
  await mockApi(page);
  await page.goto("/n/7/read/1?listen=1");
  await expect(page.getByRole("heading", { name: "Arrival" })).toBeVisible();
  await expect(page.getByText(/Test voice/i).first()).toBeVisible();
});

test("admin user quota and policy surface remains available", async ({ page }) => {
  await mockApi(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible();
  await expect(page.getByText("reader").first()).toBeVisible();
});

test("owner manage panels remain composed and reachable", async ({ page }) => {
  await mockApi(page);
  await page.goto("/n/7/manage");
  await expect(page.getByRole("heading", { name: "The Glass Tide" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
});
