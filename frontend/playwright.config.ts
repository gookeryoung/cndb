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

  // 一键起后端：数据目录隔离(.e2e-data) + seed 演示数据 + 启动 :8000。
  // reuseExistingServer 关闭：绝不复用来源不明的 8000 端口服务（可能是用户
  // 自己的后端，指向真实数据目录），保证每次运行都在隔离数据上全量重建。
  // 跨平台 Python 脚本（替代 bash/PowerShell，避免 shell 差异）。
  webServer: {
    command: "uv run python scripts/e2e-server.py",
    url: "http://127.0.0.1:8000/",
    reuseExistingServer: false,
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
      // critical 用例全部依赖登录态（匿名访问会被 ProtectedRoute 重定向到 /login），
      // anon 项目只服务 smoke 的登录/注册/登出用例，避免双倍执行与必败重试。
      testIgnore: /[\\/]critical[\\/]/,
    },
  ],
});
