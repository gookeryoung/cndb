/** 性能冒烟 —— 进表页 LCP 回归阈值.
 *
 * 指标：Largest Contentful Paint（document 生命周期口径，SPA 内工作区/表页跳转
 * 不重置，因此读数覆盖「根路径 → 表页异步数据渲染完成」全过程）。
 *
 * 阈值（ADR 0116 P3 / C10）：`min(同环境基线中位数 × 1.1, 4500ms)`。基线来自
 * `tests/e2e/perf/baselines.json` 的 `local` / `ci` 段（连续 N 轮同环境读数取中位数，
 * 由 `scripts/perf-baseline.mjs` / `perf-baseline-ci.mjs` 写入，不许手改）；基线缺失时
 * 回退 5000ms，只记录不收紧，避免把环境差异误判为回归。
 *
 * 运行方式：带 @perf 标签，CI 中从并行分片剔除、在 shard 1 内 `--workers=1` 串行
 * 独占运行——并行 worker 抢 CPU 时 LCP 读数反映的是争抢而非页面性能，无意义。
 *
 * 手动运行（独占机器，数据最可信）：
 *   pnpm e2e --project=chromium-authed tests/e2e/perf --workers=1
 */
import { test, expect } from "../fixtures/auth";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const ANON = ["setup", "chromium-anon"];

/** 硬上限（ADR 0116 C10）：比基线推导值再兜一层，真实回归一定触发，环境再抖也不放过。 */
const LCP_HARD_CAP_MS = 4500;
/** 相对基线的容差（ADR 0116 C10：中位数 +10%）。 */
const LCP_TOLERANCE = 0.1;
/** 基线缺失时回退的保守上限（与收紧前口径一致），避免没有基线就完全不设限。 */
const LCP_FALLBACK_MS = 5000;

const BASELINE_PATH = path.resolve(process.cwd(), "tests/e2e/perf", "baselines.json");

/**
 * 取本环境的 LCP 阈值（ADR 0116 P3 / C10）。
 *
 * 口径：`min(基线中位数 × 1.1, 4500)` —— 基线由 `tests/e2e/perf/baselines.json` 的
 * `local` / `ci` 段给出（连续 N 轮同环境读数取中位数，见 scripts/perf-baseline*.mjs）；
 * 基线缺失（新环境 / 尚未采集）回退 5000ms，只记录不收紧，避免把环境差异当回归。
 */
function resolveLcpLimit(): { limit: number; source: string } {
  try {
    const raw = JSON.parse(readFileSync(BASELINE_PATH, "utf8")) as {
      local?: { coldGrid?: { lcp?: number } };
      ci?: { coldGrid?: { lcp?: number } };
    };
    const env = process.env.CI ? "ci" : "local";
    const baseline = raw[env]?.coldGrid?.lcp;
    if (typeof baseline === "number" && baseline > 0) {
      const derived = Math.ceil(baseline * (1 + LCP_TOLERANCE));
      return {
        limit: Math.min(derived, LCP_HARD_CAP_MS),
        source: `${env} 基线 ${baseline}ms × ${1 + LCP_TOLERANCE} = ${derived}ms，硬上限 ${LCP_HARD_CAP_MS}ms`,
      };
    }
  } catch {
    // 基线文件缺失 / 损坏：走回退口径
  }
  return { limit: LCP_FALLBACK_MS, source: `无 ${process.env.CI ? "ci" : "local"} 基线，回退 ${LCP_FALLBACK_MS}ms` };
}

async function gotoGrid(page: Page) {
  await page.goto("/");
  await page.waitForURL(/\/w/);

  // 停留在工作区列表时，点第一行进入（GitHub 风格可折叠行列表）
  if (page.url().match(/\/w\/?$/)) {
    const firstRow = page.locator('[data-testid^="workspace-row-"]').first();
    await expect(firstRow).toBeVisible({ timeout: 10000 });
    await firstRow.locator(".cn-ws-row-main").first().click();
  }

  await page.waitForURL(/\/w\/\d+/);
  await page.getByRole("menuitem", { name: /员工表/ }).click();
  await page.waitForURL(/\/tables\/\d+/);
  // 表页主体渲染完成信号
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

test.describe("性能冒烟：进表页 LCP", () => {
  test(
    "LCP 低于基线中位数 +10%（硬上限 4500ms）",
    { tag: "@perf" },
    async ({ page }) => {
      test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");

      await gotoGrid(page);

      // 双 rAF + 200ms：等异步数据驱动的最大元素绘制落定，再从 buffered 时间线读最后一条 LCP
      await page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(resolve, 200))),
          ),
      );

      const metrics = await page.evaluate(() => {
        return new Promise<{ lcp: number; detail: string }>((resolve) => {
          let lcp = 0;
          const observer = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              if (entry.startTime > lcp) lcp = entry.startTime;
            }
          });
          observer.observe({ type: "largest-contentful-paint", buffered: true });

          setTimeout(() => {
            observer.disconnect();
            const [nav] = performance.getEntriesByType("navigation") as PerformanceNavigationTiming[];
            const fcpEntry = performance
              .getEntriesByName("first-contentful-paint")
              .at(-1);
            resolve({
              lcp,
              detail: JSON.stringify({
                ttfb: Math.round(nav.responseStart),
                fcp: fcpEntry ? Math.round(fcpEntry.startTime) : null,
                domContentLoaded: Math.round(nav.domContentLoadedEventEnd),
                load: Math.round(nav.loadEventEnd),
              }),
            });
          }, 200);
        });
      });

      // 失败时把 TTFB/FCP/DCL/load 一并带出，便于区分是后端慢还是前端渲染慢
      const { limit, source } = resolveLcpLimit();
      expect(
        metrics.lcp,
        `LCP=${Math.round(metrics.lcp)}ms，阈值 ${limit}ms（${source}），导航计时 ${metrics.detail}`,
      ).toBeLessThan(limit);
    },
  );
});
