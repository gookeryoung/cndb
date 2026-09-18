import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const _configDir = path.dirname(fileURLToPath(import.meta.url));
const AUTH_STATE = path.resolve(_configDir, ".auth/state.json");

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  workers: 8,
  reporter: [
    ["list"],
    ["./tests/e2e/reporters/slow-test.ts"],
  ],

  // 一键起后端：seed 演示数据 + 启动 :8000。本地已有后端时复用，CI 自动拉起。
  // 跨平台 Python 脚本（替代 bash/PowerShell，避免 shell 差异）。
  webServer: {
    command: "uv run python scripts/e2e-server.py",
    url: "http://127.0.0.1:8000/",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },

  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    browserName: "chromium",
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
      use: {
        storageState: AUTH_STATE,
      },
    },
    {
      name: "chromium-anon",
    },
  ],
});
