/**
 * 低配设备导出性能探针配置（opt-in，**不属于** `make e2e` 门禁）。
 *
 * 与 `playwright.config.ts` 的区别：
 * - 只跑 `tests/perf` 下的探针用例，单 worker 串行（性能测量不允许并发互扰）；
 * - Chromium 打开 `--enable-precise-memory-info`，`performance.memory` 才是未量化值；
 * - 视口固定 1366×768（低端笔记本 / 政务终端的常见分辨率）。
 *
 * 后端、登录态、baseURL 直接复用主配置，探针与 e2e 使用同一套隔离数据。
 */
import { defineConfig } from "@playwright/test";

import base from "./playwright.config";

export default defineConfig({
  ...base,
  testDir: "./tests",
  timeout: 900_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  projects: [
    { name: "setup", testMatch: /[\\/]e2e[\\/]auth\.setup\.ts/ },
    {
      name: "chromium-perf",
      dependencies: ["setup"],
      testMatch: /[\\/]tests[\\/]perf[\\/].*\.spec\.ts$/,
      use: { storageState: "./.auth/state.json" },
    },
  ],
  use: {
    ...base.use,
    viewport: { width: 1366, height: 768 },
    launchOptions: { args: ["--enable-precise-memory-info"] },
  },
});
