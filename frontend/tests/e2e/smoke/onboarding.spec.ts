/** P0 Smoke — 新手引导：首次进入自动弹出 / 关闭后写入完成标记 / 二次进入不再弹出（仅 chromium-authed）. */
import { test, expect } from "../fixtures/auth";
import type { Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];
/** 与 store/onboarding.ts 的 TOUR_STORAGE_KEY 对应（E2E 侧保持字面量，不依赖源码导出） */
const TOUR_DONE_KEY = "cndb_onboarding_done_v1";

/** 进入第一个工作区的员工表 Grid 页（与 grid.spec.ts 的 gotoGrid 同源） */
async function gotoGrid(page: Page) {
  await page.goto("/");
  await page.waitForURL(/\/w/);

  if (page.url().match(/\/w\/?$/)) {
    const workspaceCards = page.locator(".ant-card");
    await expect(workspaceCards.first()).toBeVisible({ timeout: 10000 });
    await workspaceCards.first().click();
  }

  await page.waitForURL(/\/w\/\d+/);
  await page.getByRole("menuitem", { name: /员工表/ }).click();
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

test.describe("新手引导", () => {
  test("首次进入 Grid 自动弹出引导，关闭后写入完成标记", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoGrid(page);

    // storage state 已预置完成标记，这里清除并重载以模拟首次使用
    await page.evaluate((key) => window.localStorage.removeItem(key), TOUR_DONE_KEY);
    await page.reload();
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();

    // 自动触发有 800ms 延迟，等待引导弹层出现（欢迎步骤为居中弹窗）
    const popover = page.locator(".driver-popover");
    await expect(popover).toBeVisible({ timeout: 5000 });
    await expect(popover.locator(".driver-popover-title")).toHaveText(/欢迎使用 cndb/);

    // 关闭引导 → 完成标记落盘（zustand persist 存的是 { state, version } JSON）
    await popover.locator(".driver-popover-close-btn").click();
    await expect(popover).toHaveCount(0);
    await expect
      .poll(() =>
        page.evaluate((key) => {
          const raw = window.localStorage.getItem(key);
          if (!raw) return null;
          try {
            return (JSON.parse(raw) as { state?: { tourDone?: boolean } }).state?.tourDone ?? null;
          } catch {
            return null;
          }
        }, TOUR_DONE_KEY),
      )
      .toBe(true);
  });

  test("已有完成标记时进入 Grid 不再弹出", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoGrid(page);

    // 等待超过自动触发延迟窗口（800ms），引导不应出现
    await page.waitForTimeout(1500);
    await expect(page.locator(".driver-popover")).toHaveCount(0);
    await expect
      .poll(() =>
        page.evaluate((key) => {
          const raw = window.localStorage.getItem(key);
          if (!raw) return null;
          try {
            return (JSON.parse(raw) as { state?: { tourDone?: boolean } }).state?.tourDone ?? null;
          } catch {
            return null;
          }
        }, TOUR_DONE_KEY),
      )
      .toBe(true);
  });
});
