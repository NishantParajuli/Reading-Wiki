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

async function mockApi(page, { signedIn = true, chapterData = chapter } = {}) {
  const narrationParagraphs = (chapterData.content || "").split(/\n\s*\n/);
  const timingParagraphs = [
    { source_index: null, start_ms: 0, speech_end_ms: 1000, end_ms: 1000 },
    ...narrationParagraphs.map((_, sourceIndex) => ({
      source_index: sourceIndex,
      start_ms: (sourceIndex + 1) * 1000,
      speech_end_ms: (sourceIndex + 2) * 1000,
      end_ms: (sourceIndex + 2) * 1000,
    })),
  ];
  const timing = {
    version: 1,
    duration_ms: timingParagraphs.length * 1000,
    paragraphs: timingParagraphs,
  };
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
    else if (path === "/api/activity") body = { jobs: [] };
    else if (path === "/api/novels") body = [novel];
    else if (path === "/api/discover") body = { items: [novel], total: 1, offset: 0, limit: 60 };
    else if (path === "/api/novels/7") body = novel;
    else if (path === "/api/novels/7/chapters") body = [{ number: 1, title: "Arrival" }, { number: 2, title: "Undertow" }];
    else if (path === "/api/novels/7/chapter/1") body = chapterData;
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
    else if (path === "/api/novels/7/stats") body = {
      entities: 1, facts: 1, effective_ceiling: 1, ceiling_clamped: false,
      built_chapter_count: 1, built_through_chapter: 1,
    };
    else if (path === "/api/novels/7/entities") body = [{ id: 1, canonical_name: "Mira", type: "character", first_seen_chapter: 1 }];
    else if (path === "/api/novels/7/ask") body = { answer: "Mira arrives.", citations: [], evidence_ids: [], requested_ceiling: 1, allowed_ceiling: 1, effective_ceiling: 1, ceiling_clamped: false };
    else if (path === "/api/novels/7/recap") body = { answer: "Previously, Mira arrived.", citations: [] };
    else if (path === "/api/import/jobs") body = [];
    else if (path === "/api/tts/voices") body = { voices: [{ id: "v1", name: "Test voice", ready: true }], default: "v1" };
    else if (path === "/api/novels/7/audio/coverage") body = [];
    else if (path === "/api/novels/7/chapter/1/audio/status") body = {
      cached: true, available_voices: ["v1"], timing,
    };
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
  await expect(page.getByRole("button", { name: "Choose EPUB or PDF books" })).toBeVisible();
  await expect(page.locator('input[type="file"][accept=".epub,.pdf"]'))
    .toHaveAttribute("multiple", "");
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

test("codex browser shows completed build coverage", async ({ page }) => {
  await mockApi(page);
  await page.goto("/n/7/codex");
  await expect(page.getByText("Built through Ch. 1 of 2 · 1 chapter")).toBeVisible();
});

test("cached narration controls render with mocked voice service", async ({ page }) => {
  await mockApi(page);
  await page.goto("/n/7/read/1?listen=1");
  await expect(page.getByRole("heading", { name: "Arrival" })).toBeVisible();
  await expect(page.getByText(/Test voice/i).first()).toBeVisible();
});

test("narration highlights and reveals its timed passage on mobile", async ({ page }) => {
  const content = Array.from(
    { length: 18 },
    (_, index) => `Passage ${index + 1} begins here. Its second sentence carries the story forward.`,
  ).join("\n\n");
  await page.setViewportSize({ width: 390, height: 740 });
  await mockApi(page, { chapterData: { ...chapter, content } });
  await page.goto("/n/7/read/1");

  const audio = page.locator("audio");
  await expect(audio).toBeAttached();
  await audio.evaluate((element) => {
    Object.defineProperties(element, {
      currentTime: { configurable: true, value: 17.2, writable: true },
      duration: { configurable: true, value: 100 },
      paused: { configurable: true, value: false },
      ended: { configurable: true, value: false },
    });
    element.dispatchEvent(new Event("play"));
    element.dispatchEvent(new Event("timeupdate"));
  });

  const highlighted = page.locator('[data-narration-active="true"]');
  await expect(highlighted).toHaveCount(1);
  await expect(highlighted).toContainText("Passage 17");
  await expect(highlighted).toBeInViewport();
  const background = await highlighted.evaluate(element => getComputedStyle(element).backgroundColor);
  expect(background).not.toBe("rgba(0, 0, 0, 0)");
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

test("mobile search stays reachable and restores focus after closing", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await page.goto("/library");
  const search = page.getByRole("button", { name: "Search (Ctrl+K)" });
  await search.click();
  const dialog = page.getByRole("dialog", { name: "Search", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("combobox").fill("Glass");
  await expect(dialog.getByRole("option", { name: "The Glass Tide" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(search).toBeFocused();
});

test("library errors offer recovery instead of an empty bookshelf", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/novels", route => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Temporarily unavailable" }) }));
  await page.goto("/library");
  await expect(page.getByText("Your library couldn't load")).toBeVisible();
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  await page.unroute("**/api/novels");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.locator(".shelf-card-title")).toHaveText("The Glass Tide");
  await expect(page.locator(".shelf-card a button, .shelf-card a a")).toHaveCount(0);
});

test("fresh chapters use the chapter list instead of inventing the next chapter number", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/home", route => route.fulfill({ contentType: "application/json", body: JSON.stringify({ continue_reading: [], updated_in_library: [{ ...novel, max_chapter_read: 1.5, new_chapters: 1 }], newest: [], recent_imports: [] }) }));
  await page.goto("/");
  await expect(page.locator(".newrow")).toHaveAttribute("href", "/n/7/chapters");
  await expect(page.getByRole("link", { name: "Open your library" })).toBeVisible();
});

test("scrolling never fetches an unread chapter or advances its spoiler boundary", async ({ page }) => {
  const content = Array.from({ length: 35 }, (_, i) => `Passage ${i + 1}. The story continues along the shore, with enough words to fill this reading column.`).join("\n\n");
  await mockApi(page, { chapterData: { ...chapter, content } });
  const futureRequests = [];
  page.on("request", request => { if (new URL(request.url()).pathname === "/api/novels/7/chapter/2") futureRequests.push(request.url()); });
  await page.goto("/n/7/read/1");
  await expect(page.getByRole("heading", { name: "Arrival" })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect(page.getByRole("button", { name: "Next chapter", exact: true }).first()).toBeVisible();
  await page.waitForTimeout(700);
  expect(futureRequests).toHaveLength(0);
  await expect(page).toHaveURL(/\/read\/1$/);
});


test("search keeps the active result and keyboard activation aligned", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/novels", route => route.fulfill({ json: [novel, { ...novel, id: 8, title: "A Second Shore" }] }));
  await page.goto("/library");
  await page.getByRole("button", { name: "Search (Ctrl+K)" }).click();
  const input = page.getByRole("combobox", { name: "Find a story or Codex entry" });
  const first = page.getByRole("option", { name: "The Glass Tide" });
  const second = page.getByRole("option", { name: "A Second Shore" });
  await expect(first).toBeVisible();
  await input.press("ArrowDown");
  await expect(input).toBeFocused();
  await expect(second).toHaveAttribute("aria-selected", "true");
  await expect(input).toHaveAttribute("aria-activedescendant", await second.getAttribute("id"));
  await first.focus();
  await page.keyboard.press("ArrowDown");
  await expect(second).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/n\/8$/);
});

test("activity failures are visible and recoverable", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/activity?*", route => route.fulfill({ status: 500, json: { detail: "Unavailable" } }));
  await page.goto("/");
  await expect(page.getByText("Background work couldn't load.")).toBeVisible();
  await expect(page.getByText("All quiet.", { exact: false })).toHaveCount(0);
  await page.unroute("**/api/activity?*");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("All quiet. You're ready to read.")).toBeVisible();
});
