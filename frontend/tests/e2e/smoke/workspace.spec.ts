/** P0 Smoke — 工作区列表 + 表列表（仅 chromium-authed）. */
import { test, expect } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

async function gotoWorkspace(page: any) {
  // 直接导航到已知工作区，绕过 WorkspaceList 多工作区场景
  await page.goto("/w/1/tables");
  await page.waitForURL(/\/w\/\d+\/tables/);
  // TablesList 页面
  await expect(page.getByRole("heading", { level: 3 })).toBeVisible();
}

test.describe("工作区 + 表列表", () => {
  test("主应用骨架：顶部导航 + 表列表页", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // 顶部导航
    await expect(page.getByRole("button", { name: /关系图/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /回收站/ })).toBeVisible();

    // 表列表页 — TablesList
    await expect(page.getByRole("button", { name: /新建表/ })).toBeVisible();
  });

  test("seed 数据：至少有 6 张表（某企业销售管理）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // WID=1 某企业销售管理有 6 张 seed 表
    const rows = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect(rows).toHaveCount(6);
  });
});
