#!/usr/bin/env node
/* ============================================================
   Showcase screenshots — render any route with the synthetic fixtures in
   fixtures.mjs, across themes and viewports, without a backend.

     node e2e/showcase/shoot.mjs --routes /,/library --themes dark,light \
       --viewports desktop,mobile --out /tmp/shots [--port 5190] [--full]
       [--wait 1600] [--frames 6 --every 140] [--scroll 900] [--signed-out]
       [--reduced] [--click "text=Reading settings"]

   --frames N captures N frames every --every ms right after navigation, to
   review entrance choreography. Starts its own Vite dev server.
   ============================================================ */
import { createServer } from "vite";
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { respond as respondBase, coverSvg, novels, sceneSvg } from "./fixtures.mjs";
import { respondCodex, codexArt } from "./fixtures-codex.mjs";
import { withNovelStates } from "./fixtures-novel.mjs";

// Codex answers first (ceiling-aware entities, cited answers, illustration
// plates), then the extra novel states, then the base fixtures.
const respond = withNovelStates((method, path, query) => {
  const hit = respondCodex(method, path, query);
  return hit !== undefined ? hit : respondBase(method, path, query);
});

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  if (i < 0) return fallback;
  const v = args[i + 1];
  return v == null || v.startsWith("--") ? true : v;
};

const VIEWPORTS = {
  desktop: { width: 1440, height: 900 },
  wide: { width: 1920, height: 1080 },
  laptop: { width: 1280, height: 800 },
  tablet: { width: 820, height: 1180 },
  mobile: { width: 390, height: 844 },
};

const port = Number(opt("port", 5190));
const routes = String(opt("routes", "/")).split(",").filter(Boolean);
const themes = String(opt("themes", "dark")).split(",");
const viewports = String(opt("viewports", "desktop")).split(",");
const out = resolve(String(opt("out", "/tmp/tideglass-shots")));
const full = !!opt("full", false);
const wait = Number(opt("wait", 1600));
const frames = Number(opt("frames", 0));
const every = Number(opt("every", 140));
const scroll = Number(opt("scroll", 0));
const signedOut = !!opt("signed-out", false);
const reduced = !!opt("reduced", false);
const clickSel = opt("click", null);
const clickFrames = Number(opt("click-frames", 0));
const accent = opt("accent", null);
mkdirSync(out, { recursive: true });

// A cache per port keeps concurrent showcase servers from racing on dep optimization.
const server = await createServer({ root, logLevel: "error", cacheDir: resolve(root, `node_modules/.vite-showcase-${port}`), server: { port, strictPort: true, host: "127.0.0.1" } });
await server.listen();
const base = `http://127.0.0.1:${port}`;

const browser = await chromium.launch({
  args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"],
});

const covers = new Map(novels.map(n => [n.id, n]));
const extraTitles = { 11: ["The Salt Library", "Wren Halloway"], 12: ["Emberfall", "Oren Blackwood"], 13: ["The Hollow Bell", "Mara Quill"], 14: ["Tidewrights", "Pell Aurin"] };

try {
  for (const vpName of viewports) {
    const viewport = VIEWPORTS[vpName] || VIEWPORTS.desktop;
    for (const theme of themes) {
      const context = await browser.newContext({
        viewport, deviceScaleFactor: vpName === "mobile" ? 2 : 1,
        reducedMotion: reduced ? "reduce" : "no-preference",
        hasTouch: vpName === "mobile" || vpName === "tablet",
        isMobile: vpName === "mobile",
      });
      await context.addInitScript(([t, a]) => {
        localStorage.setItem("nw-theme", t);
        localStorage.setItem("nw-reader-coached", "1");
        localStorage.setItem("nw-design", "tideglass-2");
        if (a) localStorage.setItem("nw-accent-h", a);
      }, [theme, accent]);
      await context.route(`${base}/api/**`, async (route) => {
        const url = new URL(route.request().url());
        const cover = url.pathname.match(/^\/api\/mock-covers\/(\d+)\.svg$/);
        if (cover) {
          const id = Number(cover[1]);
          const n = covers.get(id);
          const [title, author] = n ? [n.title, n.author] : (extraTitles[id] || ["Untitled", ""]);
          await route.fulfill({ contentType: "image/svg+xml", body: coverSvg(id, title, author) || "<svg xmlns='http://www.w3.org/2000/svg'/>" });
          return;
        }
        const art = codexArt(url.pathname);
        if (art) {
          await route.fulfill({ contentType: "image/svg+xml", body: art });
          return;
        }
        if (/\/illustrations\/[^/]+\/image$/.test(url.pathname)) {
          await route.fulfill({ contentType: "image/svg+xml", body: sceneSvg() });
          return;
        }
        if (signedOut && url.pathname === "/api/auth/me") {
          await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Not authenticated." }) });
          return;
        }
        const body = respond(route.request().method(), url.pathname, url.searchParams);
        await route.fulfill({ contentType: "application/json", body: JSON.stringify(body ?? {}) });
      });
      const page = await context.newPage();
      page.on("pageerror", (e) => console.error(`[pageerror] ${e.message}`));
      page.on("console", (m) => { if (m.type() === "error") console.error(`[console] ${m.text()}`); });
      for (const route of routes) {
        const slug = (route === "/" ? "home" : route.replace(/^\//, "").replace(/[/?=&]+/g, "_")) + `-${theme}-${vpName}`;
        await page.goto(base + route, { waitUntil: "domcontentloaded" });
        if (frames > 0) {
          for (let f = 0; f < frames; f++) {
            await page.waitForTimeout(every);
            await page.screenshot({ path: `${out}/${slug}-f${String(f).padStart(2, "0")}.png` });
          }
        }
        await page.waitForTimeout(wait);
        if (scroll) { await page.evaluate((y) => window.scrollTo(0, y), scroll); await page.waitForTimeout(700); }
        if (clickSel) {
          try {
            await page.locator(String(clickSel)).first().click({ timeout: 3000 });
            for (let f = 0; f < clickFrames; f++) {
              await page.waitForTimeout(every);
              await page.screenshot({ path: `${out}/${slug}-click-f${String(f).padStart(2, "0")}.png` });
            }
            await page.waitForTimeout(900);
          } catch (e) { console.error(`click failed: ${e.message}`); }
        }
        await page.screenshot({ path: `${out}/${slug}.png`, fullPage: full });
        console.log(`${out}/${slug}.png`);
      }
      await context.close();
    }
  }
} finally {
  await browser.close();
  await server.close();
}
