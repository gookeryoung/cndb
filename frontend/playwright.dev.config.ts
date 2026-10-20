/**
 * dev 模式 E2E 配置：跑在 **vite dev**（源码直出、不做摇树）上。
 *
 * 与 `playwright.config.ts`（生产构建产物）互补：
 * - 生产构建里 antd 经 Rollup 合并、绕开了 `rc-field-form` 的 es barrel；
 * - 只有 dev 会真的加载那份 barrel —— 2026-10-20 的登录页崩溃
 *   （`Cannot add property current, object is not extensible`）就只在 dev 暴露，
 *   常规 e2e 全绿也没发现。
 *
 * 所以这套配置不追求覆盖面，只兜住「依赖补丁 + ESM 语义 + 表单 ref 链路」此类
 * 只在 dev 才会现形的回归。用例少而精，单 worker 串行。
 */
import { defineConfig } from "@playwright/test";

const DEV_PORT = 5175;
const DEV_BASE = `http://127.0.0.1:${DEV_PORT}`;

export default defineConfig({
  testDir: "./tests/e2e/dev",
  // dev 下首次请求会按需编译大量模块（antd 尤甚），比生产产物慢一个量级
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  webServer: {
    // 只托管被测 API：隔离后端（.e2e-data + seed）。
    // vite dev 由用例的 beforeAll 托管（见 tests/e2e/dev/start-dev-server.ts）——
    // Playwright 的 webServer 探活在 Windows + pnpm exec 包装下不可靠
    //（实测探活命中后进程仍可能退场，用例一开始就 ERR_CONNECTION_REFUSED），
    // 自托管 + 显式轮询端口是最稳的做法。
    command: "uv run python scripts/e2e-server.py",
    url: "http://127.0.0.1:8000/",
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
  use: {
    baseURL: DEV_BASE,
    browserName: "chromium",
    headless: true,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
});
