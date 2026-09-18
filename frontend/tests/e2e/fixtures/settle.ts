/** settle.ts — 信号化等待收敛出口.
 *
 * 背景：E2E 速度优化（A1）逐步把硬编码 `page.waitForTimeout(N)` 迁移为确定性信号等待
 * （expect(...).toBeVisible / waitForResponse / 等 spinner）。动画类视图（甘特/日历/看板
 * 拖拽、视图切换渲染）在缺少清晰 DOM 信号处，残余短延迟统一收敛到此函数，便于审计、
 * 全局收紧与后续彻底移除。
 *
 * 实现：先等两个 rAF 让 React/antd 副作用与持久化 mutation 落定，再按需做一次可控短延时。
 */
import type { Page } from "@playwright/test";

/**
 * 等页面动画/副作用收敛。
 * @param page 当前 page 实例
 * @param ms 残余动画时长；默认 0（仅双 rAF + 一次空转，约几十毫秒，远小于原 300~2500ms）
 */
export async function settle(page: Page, ms = 0): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  if (ms > 0) {
    await page.waitForTimeout(ms);
  }
}