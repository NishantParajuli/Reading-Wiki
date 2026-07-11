import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";

test.describe("real browser-to-backend contract", () => {
  test.skip(!process.env.REAL_BACKEND, "requires disposable PostgreSQL and FastAPI on :8001");
  test.describe.configure({ mode: "serial", timeout: 120_000 });

  const password = "browser-pass-123";

  async function register(page, username) {
    await page.goto("/register");
    await page.getByLabel("Email").fill(`${username}@example.test`);
    await page.getByLabel("Username").fill(username);
    await page.getByText("Password", { exact: true }).locator("..").locator("input").fill(password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/$/);
  }

  async function login(page, username) {
    await page.goto("/login");
    await page.getByLabel(/email or username/i).fill(username);
    await page.getByText("Password", { exact: true }).locator("..").locator("input").fill(password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/(?:library)?$/);
  }

  async function api(page, path, { method = "GET", body, headers = {} } = {}) {
    return page.evaluate(async ({ path, method, body, headers }) => {
      const csrf = document.cookie.split(";").map((v) => v.trim().split("="))
        .find(([name]) => name === "tg_csrf")?.[1];
      const response = await fetch(path, {
        method, credentials: "same-origin",
        headers: {
          ...(body === undefined ? {} : { "content-type": "application/json" }),
          ...(method === "GET" ? {} : { "x-csrf-token": decodeURIComponent(csrf || "") }),
          ...headers,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await response.text();
      let payload = text;
      try { payload = JSON.parse(text); } catch { /* binary/text response */ }
      return { status: response.status, headers: Object.fromEntries(response.headers), body: payload };
    }, { path, method, body, headers });
  }

  async function pollJob(page, jobId, wanted) {
    await expect.poll(async () => (await api(page, `/api/import/jobs/${jobId}`)).body.status,
      { timeout: 45_000 }).toBe(wanted);
    return (await api(page, `/api/import/jobs/${jobId}`)).body;
  }

  test("nine required real-backend paths", async ({ browser }) => {
    const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
    const owner = `browser_${suffix}`;
    const viewer = `viewer_${suffix}`;
    const ownerContext = await browser.newContext();
    const viewerContext = await browser.newContext();
    const ownerPage = await ownerContext.newPage();
    const viewerPage = await viewerContext.newPage();
    let fixture;

    await test.step("1. register/login/logout and session re-gate", async () => {
      await register(ownerPage, owner);
      await api(ownerPage, "/api/auth/logout", { method: "POST", body: {} });
      await ownerPage.goto("/library");
      await expect(ownerPage).toHaveURL(/\/login$/);
      await login(ownerPage, owner);
    });

    await test.step("2. create/add novel and verify Library plus Discover", async () => {
      const title = `Real backend ${suffix}`;
      const created = await api(ownerPage, "/api/novels", { method: "POST", body: {
        title, description: "Created through the real browser/API boundary.",
        original_language: "en", codex_enabled: false,
      }});
      expect(created.status).toBe(200);
      expect((await api(ownerPage, `/api/novels/${created.body.id}/visibility`, {
        method: "PATCH", body: { visibility: "public" },
      })).status).toBe(200);
      await ownerPage.goto("/library");
      await expect(ownerPage.getByText(title).first()).toBeVisible();
      await register(viewerPage, viewer);
      await viewerPage.goto("/discover");
      await expect(viewerPage.getByText(title).first()).toBeVisible();

      fixture = JSON.parse(execFileSync("uv", ["run", "python", "scripts/real_browser_fixture.py",
        "--username", owner, "--suffix", suffix], { cwd: resolve("../.."), encoding: "utf8" }));
    });

    await test.step("3. read chapter and persist trusted progress plus bookmark", async () => {
      const chapter = await api(ownerPage, `/api/novels/${fixture.novel_id}/chapter/1`);
      expect(chapter.status).toBe(200);
      expect(chapter.body.content).toContain("real backend boundary");
      expect((await api(ownerPage, `/api/novels/${fixture.novel_id}/progress`, {
        method: "PUT", body: { last_chapter: 1, scroll_pct: 47.5 },
      })).status).toBe(200);
      const bookmark = await api(ownerPage, `/api/novels/${fixture.novel_id}/bookmarks`, {
        method: "POST", body: { chapter: 1, note: "real browser bookmark" },
      });
      expect(bookmark.status).toBe(200);
      const progress = await api(ownerPage, `/api/novels/${fixture.novel_id}/progress`);
      expect(progress.body).toMatchObject({ last_chapter: 1, max_chapter_read: 1, scroll_pct: 47.5 });
      expect((await api(ownerPage, `/api/novels/${fixture.novel_id}/bookmarks`)).body)
        .toEqual(expect.arrayContaining([expect.objectContaining({ note: "real browser bookmark" })]));
    });

    await test.step("4. save, conflict, resolve and revert an overlay", async () => {
      expect((await api(viewerPage, `/api/novels/${fixture.novel_id}/chapter/1/overlay`, {
        method: "PUT", body: { content: "Viewer overlay fixture" },
      })).status).toBe(200);
      expect((await api(ownerPage, `/api/novels/${fixture.novel_id}/chapter/1/content`, {
        method: "PUT", body: { content: "Owner changed the fixture base." },
      })).status).toBe(200);
      expect((await api(viewerPage, `/api/novels/${fixture.novel_id}/chapter/1`)).body.overlay_conflict).toBe(true);
      expect((await api(viewerPage, `/api/novels/${fixture.novel_id}/chapter/1/resolve`, {
        method: "POST", body: { choice: "mine", content: null },
      })).status).toBe(200);
      expect((await api(viewerPage, `/api/novels/${fixture.novel_id}/chapter/1/overlay`, {
        method: "DELETE",
      })).status).toBe(200);
      expect((await api(viewerPage, `/api/novels/${fixture.novel_id}/chapter/1`)).body.overlay).toBe(false);
    });

    await test.step("5. upload EPUB through review and commit", async () => {
      const epub = resolve("e2e/.real-backend-fixture.epub");
      execFileSync("uv", ["run", "python", "scripts/real_browser_fixture.py", "--make-epub",
        resolve("novelwiki/frontend", epub)], { cwd: resolve("../..") });
      const bytes = readFileSync(epub).toString("base64");
      const upload = await ownerPage.evaluate(async (base64) => {
        const raw = atob(base64); const data = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i += 1) data[i] = raw.charCodeAt(i);
        const form = new FormData();
        form.append("file", new File([data], "browser-fixture.epub", { type: "application/epub+zip" }));
        const csrf = document.cookie.split(";").map((v) => v.trim().split("="))
          .find(([name]) => name === "tg_csrf")?.[1];
        const response = await fetch("/api/import/upload", { method: "POST", credentials: "same-origin",
          headers: { "x-csrf-token": decodeURIComponent(csrf || "") }, body: form });
        return { status: response.status, body: await response.json() };
      }, bytes);
      rmSync(epub, { force: true });
      expect(upload.status).toBe(200);
      const reviewed = await pollJob(ownerPage, upload.body.id, "awaiting_review");
      expect(reviewed.plan.segments.length).toBeGreaterThan(0);
      expect((await api(ownerPage, `/api/import/jobs/${upload.body.id}/commit`, {
        method: "POST", body: { mode: "new", offset: 0, is_raw: false },
      })).status).toBe(200);
      const committed = await pollJob(ownerPage, upload.body.id, "committed");
      expect(committed.novel_id).toBeGreaterThan(0);
    });

    await test.step("6. cancel a durable job and observe Activity", async () => {
      const canceled = await api(ownerPage, `/api/jobs/${fixture.job_id}/cancel`, { method: "POST", body: {} });
      expect(canceled.body).toMatchObject({ status: "success", canceled: true });
      const activity = await api(ownerPage, "/api/activity?status=all");
      expect(activity.body.jobs).toEqual(expect.arrayContaining([
        expect.objectContaining({ id: fixture.job_id, source: "job", status: "canceled" }),
      ]));
    });

    await test.step("7. issue cached Codex Ask at a trusted ceiling", async () => {
      const asked = await api(ownerPage, `/api/novels/${fixture.novel_id}/ask`, {
        method: "POST", body: { question: fixture.question, ceiling: 99 },
      });
      expect(asked.status).toBe(200);
      expect(asked.body.answer).toContain("browser/backend boundary");
      expect(asked.body.effective_ceiling).toBe(1);
      expect(asked.body.ceiling_clamped).toBe(true);
    });

    await test.step("8. load authorized cached audio with a byte range", async () => {
      const audio = await ownerPage.evaluate(async ({ novelId, voice }) => {
        const response = await fetch(`/api/novels/${novelId}/chapter/1/audio.opus?voice_id=${voice}`,
          { credentials: "same-origin", headers: { Range: "bytes=0-7" } });
        return { status: response.status, length: (await response.arrayBuffer()).byteLength,
          range: response.headers.get("content-range"), cache: response.headers.get("cache-control") };
      }, { novelId: fixture.novel_id, voice: fixture.voice_id });
      expect(audio.status).toBe(206);
      expect(audio.length).toBe(8);
      expect(audio.range).toContain("bytes 0-7/");
      expect(audio.cache).toContain("private");
    });

    await test.step("9. perform an admin user/quota action", async () => {
      const viewerRow = (await api(ownerPage, `/api/admin/users?q=${viewer}`)).body
        .find((row) => row.username === viewer);
      expect(viewerRow).toBeTruthy();
      const changed = await api(ownerPage, `/api/admin/users/${viewerRow.id}`, {
        method: "PATCH", body: { quota_tts_chapters: 7 },
      });
      expect(changed.body.status).toBe("success");
      const refreshed = (await api(ownerPage, `/api/admin/users?q=${viewer}`)).body
        .find((row) => row.username === viewer);
      expect(refreshed.limits.tts_chapters).toBe(7);
    });

    await ownerContext.close();
    await viewerContext.close();
  });
});
