import { expect, test } from "@playwright/test";

for (const [layout, viewport] of [["desktop", { width: 1440, height: 1000 }], ["mobile", { width: 390, height: 844 }]]) {
  test(`Novelpia cookie replacement is private and usable on ${layout}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    let stored = {
      configured: true, usable: true, updated_at: "2026-09-27T10:00:00Z",
      cookies: [{ name: "TKEY", domain: ".novelpia.com", expires_at: "2027-09-27T10:00:00Z" }],
    };
    let unreadable = false;
    const writes = [];
    await page.route("http://127.0.0.1:4173/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let body = {};
      if (path === "/api/auth/me") body = { id: 1, username: "reader", role: "admin", status: "active", email_verified: true, prefs: {} };
      else if (path === "/api/auth/links") body = { linked: [], has_password: true };
      else if (path === "/api/settings/novelpia-cookies") {
        if (unreadable && route.request().method() === "GET") {
          await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "Saved Novelpia cookies cannot be opened." }) });
          return;
        }
        if (route.request().method() === "PUT") {
          writes.push(route.request().postDataJSON());
          stored = { configured: true, usable: true, updated_at: "2026-09-27T10:00:00Z", cookies: [{ name: "TKEY", domain: ".novelpia.com", expires_at: null }] };
        }
        if (route.request().method() === "DELETE") stored = { configured: false, usable: false, updated_at: null, cookies: [] };
        body = stored;
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto("/account/sources");
    const panel = page.getByRole("region", { name: "Novelpia Global" });
    await expect(panel.getByLabel("Replace cookies")).toHaveValue("");
    await page.getByText("Saved cookie expiry dates").click();
    await expect(panel.getByText("TKEY", { exact: true })).toBeVisible();
    await page.getByText("How to get your cookies").click();
    if (layout === "mobile") await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await page.screenshot({ path: `../../.impeccable/review/novelpia-settings-${layout}.png`, fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
    await panel.getByLabel("Replace cookies").fill('[{"name":"TKEY","domain":".novelpia.com","value":"synthetic-token"}]');
    await panel.getByRole("button", { name: "Replace cookies" }).click();
    await expect(panel.getByRole("status")).toContainText("Cookies saved");
    await expect(panel.getByLabel("Replace cookies")).toHaveValue("");
    expect(writes).toEqual([{ cookies: [{ name: "TKEY", domain: ".novelpia.com", value: "synthetic-token" }] }]);
    await panel.getByRole("button", { name: "Remove saved cookies" }).click();
    await expect(panel.getByText("No cookies saved")).toBeVisible();
    await expect(panel.getByLabel("Cookie export")).toHaveValue("");
    unreadable = true;
    await page.reload();
    await expect(panel.getByRole("alert")).toContainText("saved cookies cannot be opened");
    await expect(panel.getByRole("button", { name: "Remove saved cookies" })).toBeEnabled();
    await panel.getByLabel("Cookie export").fill('[{"name":"TKEY","domain":".novelpia.com","value":"synthetic-replacement"}]');
    await panel.getByRole("button", { name: "Save cookies" }).click();
    await expect(panel.getByRole("alert")).toHaveCount(0);
    await expect(panel.getByRole("status")).toContainText("Cookies saved");
    expect(writes).toHaveLength(2);
  });
}
