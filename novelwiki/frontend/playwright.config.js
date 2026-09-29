import { defineConfig, devices } from "@playwright/test";

const realBackend = process.env.REAL_BACKEND === "1";
const frontendPort = realBackend ? 4174 : 4173;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
    url: `http://127.0.0.1:${frontendPort}`,
    // Never inherit a developer server's proxy when qualifying a disposable DB.
    reuseExistingServer: !process.env.CI && !realBackend,
  },
});
