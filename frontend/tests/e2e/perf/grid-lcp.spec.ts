/** 性能冒烟 —— 进表页 LCP 回归阈值.
 *
 * 指标：Largest Contentful Paint（document 生命周期口径，SPA 内工作区/表页跳转
 * 不重置，因此读数覆盖「根路径 → 表页异步数据渲染完成」全过程）。
 *
 * 阈值 3000ms：本地单机（CI 同款 webServer 架构，后端 + 浏览器同机）基线远低于此；
 * CI e2e job 当前为 continue-on-error 观察期且 8 worker 并行抢 CPU，本用例先随
 * 观察期收集波动数据，待并行度/基线稳定后再把阈值固化为硬门禁。
 *
 * 手动运行（独占机器，数据最可信）：
 *   pnpm e2e --project=chromium-authed tests/e2e/perf
 */
import { test, expect } from "../fixtures/auth";
import type { Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
const LCP_LIMIT_MS = 3000;

async function gotoGrid(page: Page) {
  await page.goto("/");
  await page.waitForURL(/\/w/);

  // 停留在工作区列表时，点第一张卡片进入
  if (page.url().match(/\/w\/?$/)) {
    const workspaceCards = page.locator(".ant-card");
    await expect(workspaceCards.first()).toBeVisible({ timeout: 10000 });
    await workspaceCards.first().click();
  }

  await page.waitForURL(/\/w\/\d+/);
  await page.getByRole("menuitem", { name: /员工表/ }).click();
  await page.waitForURL(/\/tables\/\d+/);
  // 表页主体渲染完成信号
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

test.describe("性能冒烟：进表页 LCP", () => {
  test("LCP 低于 3000ms", async ({ page }) => {
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
    expect(metrics.lcp, `LCP=${Math.round(metrics.lcp)}ms，导航计时 ${metrics.detail}`).toBeLessThan(
      LCP_LIMIT_MS,
    );
  });
});
