import { defineConfig, devices } from "@playwright/test";

/** End-to-end journeys against the static demo build (MSW answers the API), on desktop and phone sizes. */
const base = process.env.E2E_BASE_PATH ?? "";

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  // reduced motion: axe must not sample colours halfway through a CSS transition
  use: { baseURL: `http://127.0.0.1:3100${base}/`, trace: "retain-on-failure", contextOptions: { reducedMotion: "reduce" } },
  webServer: {
    // E2E_BASE_PATH mirrors GitHub Pages, which serves the demo under /<repository>/
    command: `python e2e/serve.py 3100 out ${base}`,
    url: `http://127.0.0.1:3100${base}/`,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
