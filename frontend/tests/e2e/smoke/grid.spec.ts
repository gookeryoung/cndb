/** P0 Smoke — Grid 表格渲染与基础操作（仅 chromium-authed）. */
import { test, expect } from "../fixtures/auth";
import type { Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

async function gotoGrid(page: Page) {
  // 先进入应用根路径（登录后）
  await page.goto("/");

  // 等待离开登录页
  await page.waitForURL(/\/w/);

  // 如果停留在 /w（工作区列表），则点击第一个工作区卡片进入
  if (page.url().match(/\/w\/?$/)) {
    // 等待工作区卡片加载
    const workspaceCards = page.locator(".ant-card");
    await expect(workspaceCards.first()).toBeVisible({ timeout: 10000 });
    await workspaceCards.first().click();
  }

  // 现在应该在某个工作区下
  await page.waitForURL(/\/w\/\d+/);

  // 侧栏 Menu 点击 "员工表"
  await page.getByRole("menuitem", { name: /员工表/ }).click();

  // 等待 Grid 加载
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

test.describe("Grid 表格", () => {
  test("Grid 骨架：工具栏 + Antd Table", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoGrid(page);

    // 工具栏
    await expect(page.getByRole("button", { name: /返回/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();

    // Antd Table
    await expect(page.locator(".ant-table")).toBeVisible();
  });

  test("员工表有 5 条 seed 记录", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoGrid(page);

    // 分页 showTotal 渲染信号（虚拟滚动下行 DOM 不固定为 tr.ant-table-row）。
    // 总数不锁死 5：row-crud.spec.ts 与本文件跨文件并行，其 CRUD 窗口内总数
    // 会瞬时为 6；精确计数断言由同文件串行执行的 row-crud 用例持有。
    await expect(page.getByText(/共 \d+ 条/)).toBeVisible();
    // 5 条 seed 姓名逐行可见 —— 比单一计数更确定性地证明 seed 完整（可查出缺行）
    for (const name of ["张三", "李四", "王五", "赵六", "钱七"]) {
      await expect(page.getByText(name).first()).toBeVisible();
    }
  });
});
