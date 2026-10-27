import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const _configDir = path.dirname(fileURLToPath(import.meta.url));
const AUTH_STATE = path.resolve(_configDir, ".auth/state.json");

// 本机 8000 被其他服务占用时可用 E2E_PORT 换端口；CI / 默认仍是 8000
const E2E_PORT = process.env.E2E_PORT ?? "8000";
const E2E_BASE_URL = `http://127.0.0.1:${E2E_PORT}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  retries: process.env.CI ? 2 : 0,
  // worker 固定 4：CI runner 通常 4 vCPU；本机高并发下超时失败明显，4 worker 最稳。
  // E2E 已为门禁，稳定性优先于并行度。
  workers: 4,
  reporter: [
    ["list"],
    ["./tests/e2e/reporters/slow-test.ts"],
    // CI 失败时上传的可读报告；outputFolder 与 workflow 的 artifact 路径保持一致
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],

  // 一键起后端：.e2e-data 隔离 + seed + 起 :8000（E2E_PORT 可换端口）。reuseExistingServer
  // 关闭，绝不复用来源不明的 8000 服务，保证每次在隔离数据上全量重建。跨平台 Python 脚本（避免 shell 差异）。
  webServer: {
    command: "uv run python scripts/e2e-server.py",
    url: `${E2E_BASE_URL}/`,
    reuseExistingServer: false,
    timeout: 120_000,
  },

  use: {
    baseURL: E2E_BASE_URL,
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
      // dev 用例（tests/e2e/dev/*）只由 playwright.dev.config.ts（pnpm e2e:dev）托管：
      // 其 beforeAll 起 vite dev、afterAll 杀进程会触发 sync-static 的 closeBundle，
      // 而该钩子在缺 frontend/dist 时会清空 src/cndb/static（CI 产物由 artifact 灌入），
      // 抹掉同分片后续用例的页面 → 整片 404。分片随机承载 dev 用例，故必须全局排除。
      testIgnore: /[\\/]dev[\\/]/,
      dependencies: ["setup"],
      use: {
        storageState: AUTH_STATE,
      },
    },
    {
      name: "chromium-anon",
      // critical 用例全部依赖登录态（匿名访问会被 ProtectedRoute 重定向到 /login），
      // anon 项目只服务 smoke 的登录/注册/登出用例，避免双倍执行与必败重试；
      // dev 用例同 authed 项目一并排除（原因见上）。
      testIgnore: /[\\/](critical|dev)[\\/]/,
    },
  ],
});
