import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],

  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        executablePath: "/root/.cache/puppeteer/chrome/linux-151.0.7922.71/chrome-linux64/chrome",
      },
    },
    {
      name: "chromium-authed",
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        executablePath: "/root/.cache/puppeteer/chrome/linux-151.0.7922.71/chrome-linux64/chrome",
        storageState: ".auth/state.json",
      },
    },
    {
      name: "chromium-anon",
      use: {
        ...devices["Desktop Chrome"],
        executablePath: "/root/.cache/puppeteer/chrome/linux-151.0.7922.71/chrome-linux64/chrome",
      },
    },
  ],
});
