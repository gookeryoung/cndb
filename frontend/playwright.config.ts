/** Playwright 配置：复用已启动后端服务，独立 e2e 数据层.
 *
 * 使用系统 Edge 浏览器（channel: msedge），无需下载 Playwright 自带 Chromium.
 * 如需切换为 Playwright Chromium：
 *   npx playwright install chromium
 *   然后把 channel: "msedge" 去掉即可.
 */
import { defineConfig, devices } from "@playwright/test";

const _EDGE = { ...devices["Desktop Chrome"], channel: "msedge" };

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 20_000,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],

  // 单一配置源：baseURL 从环境变量覆盖，默认 8000
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  // 不复用 webServer 自启 — 手动启动: uv run cndb serve --host 127.0.0.1 --port 8000
  // 数据初始化: uv run cndb seed

  projects: [
    // 登录 setup：一次表单登录 → 持久化 StorageState
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
      use: {
        ..._EDGE,
      },
    },
    {
      name: "chromium-authed",
      dependencies: ["setup"],
      use: {
        ..._EDGE,
        storageState: ".auth/state.json",
      },
    },
    // 匿名项目（公开表单/共享视图）
    {
      name: "chromium-anon",
      use: {
        ..._EDGE,
      },
    },
  ],
});
