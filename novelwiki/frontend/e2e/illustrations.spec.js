import { expect, test } from "@playwright/test";

for (const [layout, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]]) {
  test(`chapter illustration controls stay explicit and usable on ${layout}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript(() => localStorage.setItem("nw-reader-coached", "1"));
    let started = false;
    const requests = [];
    await page.route("http://127.0.0.1:4173/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let body = {};
      if (path === "/api/auth/me") body = { id: 1, username: "reader", role: "admin", status: "active", email_verified: true, prefs: {} };
      else if (path === "/api/novels/7") body = { id: 7, title: "The Glass Tide", is_owner: true, progress: { max_chapter_read: 1 } };
      else if (path === "/api/novels/7/chapter/1") body = { number: 1, title: "Arrival", content: "The tide reached the glass shore. Mira waited for the water to settle before taking her first step.", prev: null, next: 2 };
      else if (path === "/api/novels/7/progress") body = { last_chapter: 1, scroll_pct: 0 };
      else if (path === "/api/novels/7/bookmarks") body = [];
      else if (path === "/api/tts/voices") body = { voices: [], default: null };
      else if (path === "/api/novels/7/audio/coverage") body = [];
      else if (path.endsWith("/audio/status")) body = { cached: false, available_voices: [] };
      else if (path === "/api/novels/7/chapters/1/illustrations") {
        if (route.request().method() === "POST") {
          requests.push(route.request().postDataJSON());
          started = true;
          body = { job_id: "job-1" };
        } else body = { items: [], can_generate: true, active_job: started ? { id: "job-1", status: "running" } : null };
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/n/7/read/1");
    const toggle = page.getByRole("button", { name: /Illustrate this chapter/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    const panel = page.getByRole("region", { name: "Chapter illustrations" });
    await expect(panel.getByRole("button", { name: "Generate illustrations" })).toBeVisible();
    await expect(panel.getByLabel("Scenes")).toHaveCount(0);
    await panel.getByLabel("Art style").selectOption("celestial");
    expect(requests).toEqual([]);
    await panel.scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: `../../.impeccable/review/illustrations-${layout}.png`, fullPage: true });
    const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(hasOverflow).toBe(false);
    await panel.getByRole("button", { name: "Generate illustrations" }).click();
    expect(requests).toEqual([{ style: "celestial", force: false }]);
    await expect(panel.getByRole("button", { name: "Generate illustrations" })).toBeDisabled();
    await expect(panel.getByRole("link", { name: "View jobs" })).toHaveAttribute("href", "/jobs");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(requests).toHaveLength(1);
  });
}

for (const [layout, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]]) {
  test(`range generation and inline reading work on ${layout}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.addInitScript(() => localStorage.setItem("nw-reader-coached", "1"));
    const requests = [];
    const paragraphs = ["Mira entered the city as the evening bells began to sound. The harbor was still bright with the last gold of sunset.", "She stopped beside the old stone bridge. Beneath it, a thousand lanterns drifted slowly toward the sea.", "For the first time since leaving home, she knew which road she wanted to take."];
    const novel = { id: 7, title: "The Glass Tide", can_edit: true, is_owner: true, codex_enabled: false, sources: [], status_tags: [], chapter_count: 100, min_chapter: 1, max_chapter: 100, progress: { last_chapter: 25, max_chapter_read: 25 } };
    await page.route("http://127.0.0.1:4173/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let body = {};
      if (path === "/api/auth/me") body = { id: 1, username: "reader", role: "admin", status: "active", email_verified: true, prefs: {} };
      else if (path === "/api/novels/7") body = novel;
      else if (path === "/api/novels/7/chapter/25") body = { number: 25, title: "The Lantern Road", content: paragraphs.join("\n\n"), prev: 24, next: 26 };
      else if (path === "/api/novels/7/progress") body = { last_chapter: 25, scroll_pct: 0 };
      else if (path === "/api/novels/7/chapters/25/illustrations") body = { can_generate: true, items: [{ id: "scene-25", kind: "scene", title: "Lanterns on the tide", caption: "Mira pauses at the stone bridge.", style: "luminous", placement: { position: "after", anchor: "a thousand lanterns drifted slowly toward the sea" }, image_url: "/api/novels/7/illustrations/scene-25/image" }] };
      else if (path.endsWith("/scene-25/image")) {
        await route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800"><rect width="1200" height="800" fill="#183d35"/><text x="600" y="400" text-anchor="middle" fill="#f1eee3" font-size="36">Chapter illustration · test fixture</text></svg>' }); return;
      }
      else if (path === "/api/novels/7/illustrations") {
        if (route.request().method() === "POST") { requests.push(route.request().postDataJSON()); body = { job_id: "range-25-100", created: true, chapter_count: 76 }; }
        else body = { can_generate: true, active_job: null };
      }
      else if (path === "/api/jobs") body = { jobs: [] };
      else if (path === "/api/novels/7/health") body = { codex: { entities: 0, missing: true }, untranslated_raw_chapters: 0, total_chapters: 100, recent_errors: [] };
      else if (path === "/api/tts/voices") body = { voices: [], default: null };
      else if (/\/(bookmarks|contributions|tag-suggestions|glossary|chapters|coverage)$/.test(path)) body = [];
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/n/7/manage");
    const panel = page.getByRole("region", { name: "Illustrate ahead" });
    await expect(panel.getByLabel("From chapter")).toHaveValue("25");
    await panel.getByLabel("Through chapter").fill("100");
    await expect(panel.getByRole("checkbox")).not.toBeChecked();
    await panel.scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: `../../.impeccable/review/illustration-range-${layout}.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await panel.getByRole("button", { name: "Illustrate chapters" }).click();
    expect(requests).toEqual([{ from_chapter: 25, to_chapter: 100, style: "luminous", force: false }]);
    await expect(panel.getByRole("link", { name: "View progress in Jobs" })).toBeVisible();
    await page.goto("/n/7/read/25");
    const figure = page.locator(".reader-text .chapter-art-inline");
    await expect(figure).toBeVisible();
    expect(await figure.evaluate(node => node.previousElementSibling.textContent)).toBe(paragraphs[1]);
    expect(await figure.evaluate(node => node.nextElementSibling.textContent)).toBe(paragraphs[2]);
    await expect(page.getByRole("button", { name: /Illustrate this chapter/ })).toHaveAttribute("aria-expanded", "false");
    expect(await page.locator("[data-narration-chunk]").count()).toBeGreaterThanOrEqual(3);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: `../../.impeccable/review/illustration-inline-${layout}.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  });
}
