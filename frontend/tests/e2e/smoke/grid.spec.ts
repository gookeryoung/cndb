/** P0 Smoke — Grid 表格渲染与基础操作（仅 chromium-authed）. */
import { test, expect } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

async function gotoGrid(page: any) {
  // 先进入工作区表列表
  await page.goto("/");
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

    // 等待数据加载
    await page.waitForTimeout(800);

    // Antd Table body 应该有 5 行
    const rows = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect(rows).toHaveCount(5);
  });
});
