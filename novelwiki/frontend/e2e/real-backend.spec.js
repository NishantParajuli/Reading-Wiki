import { expect, test } from "@playwright/test";

test.describe("real browser-to-backend contract", () => {
  test.skip(!process.env.REAL_BACKEND, "requires disposable PostgreSQL and FastAPI on :8001");

  test("register, create/catalog, logout, login and session re-gate", async ({ page }) => {
    const suffix = `${Date.now()}${Math.floor(Math.random() * 1000)}`;
    const username = `browser_${suffix}`;
    const email = `${username}@example.test`;
    const password = "browser-pass-123";
    const title = `Real backend ${suffix}`;

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Username").fill(username);
    await page.getByText("Password", { exact: true }).locator("..").locator("input").fill(password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/$/);

    const created = await page.evaluate(async (novelTitle) => {
      const csrf = document.cookie
        .split(";")
        .map((value) => value.trim().split("="))
        .find(([name]) => name === "tg_csrf")?.[1];
      const response = await fetch("/api/novels", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": decodeURIComponent(csrf || ""),
        },
        body: JSON.stringify({
          title: novelTitle,
          description: "Created through the real browser/API boundary.",
          original_language: "en",
          codex_enabled: false,
        }),
      });
      const body = await response.json();
      if (response.ok) {
        const visibility = await fetch(`/api/novels/${body.id}/visibility`, {
          method: "PATCH",
          credentials: "same-origin",
          headers: {
            "content-type": "application/json",
            "x-csrf-token": decodeURIComponent(csrf || ""),
          },
          body: JSON.stringify({ visibility: "public" }),
        });
        if (!visibility.ok) throw new Error(`visibility update failed: ${visibility.status}`);
      }
      return { status: response.status, body };
    }, title);
    expect(created.status).toBe(200);
    expect(created.body.id).toBeGreaterThan(0);

    await page.goto("/library");
    await expect(page.getByText(title).first()).toBeVisible();
    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByText("Sign out", { exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);

    const viewer = `viewer_${suffix}`;
    await page.goto("/register");
    await page.getByLabel("Email").fill(`${viewer}@example.test`);
    await page.getByLabel("Username").fill(viewer);
    await page.getByText("Password", { exact: true }).locator("..").locator("input").fill(password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.goto("/discover");
    await expect(page.getByText(title).first()).toBeVisible();
    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByText("Sign out", { exact: true }).click();

    await page.getByLabel(/email or username/i).fill(username);
    await page.getByText("Password", { exact: true }).locator("..").locator("input").fill(password);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.goto("/library");
    await expect(page.getByText(title).first()).toBeVisible();

    await page.evaluate(async () => {
      const csrf = document.cookie
        .split(";")
        .map((value) => value.trim().split("="))
        .find(([name]) => name === "tg_csrf")?.[1];
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": decodeURIComponent(csrf || ""),
        },
        body: "{}",
      });
    });
    await page.goto("/library");
    await expect(page).toHaveURL(/\/login$/);
  });
});
