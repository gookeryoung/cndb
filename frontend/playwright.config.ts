import { defineConfig, devices } from "@playwright/test";

const CHROME_PATH = "/root/.cache/puppeteer/chrome/linux-151.0.7922.71/chrome-linux64/chrome";

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
        executablePath: CHROME_PATH,
      },
    },
    {
      name: "chromium-authed",
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        executablePath: CHROME_PATH,
        storageState: ".auth/state.json",
      },
    },
    {
      name: "chromium-anon",
      use: {
        ...devices["Desktop Chrome"],
        executablePath: CHROME_PATH,
      },
    },
  ],
});
