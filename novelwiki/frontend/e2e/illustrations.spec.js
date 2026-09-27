import { expect, test } from "@playwright/test";

for (const [layout, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]]) {
  test(`chapter illustration controls stay explicit and usable on ${layout}`, async ({ page }) => {
    await page.setViewportSize(viewport);
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
    await panel.getByLabel("Scenes").selectOption("2");
    await panel.getByLabel("Art style").selectOption("celestial");
    expect(requests).toEqual([]);
    await panel.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `../../.impeccable/review/illustrations-${layout}.png`, fullPage: true });
    const hasOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(hasOverflow).toBe(false);
    await panel.getByRole("button", { name: "Generate illustrations" }).click();
    expect(requests).toEqual([{ count: 2, style: "celestial", force: false }]);
    await expect(panel.getByRole("button", { name: "Generate illustrations" })).toBeDisabled();
    await expect(panel.getByRole("link", { name: "View jobs" })).toHaveAttribute("href", "/jobs");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(requests).toHaveLength(1);
  });
}
