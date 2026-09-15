import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const _configDir = path.dirname(fileURLToPath(import.meta.url));
const CHROME_PATH = "/root/.cache/puppeteer/chrome/linux-151.0.7922.71/chrome-linux64/chrome";
const AUTH_STATE = path.resolve(_configDir, ".auth/state.json");

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
    browserName: "chromium",
    executablePath: CHROME_PATH,
    headless: true,
  },

  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium-authed",
      dependencies: ["setup"],
      storageState: AUTH_STATE,
    },
    {
      name: "chromium-anon",
    },
  ],
});
