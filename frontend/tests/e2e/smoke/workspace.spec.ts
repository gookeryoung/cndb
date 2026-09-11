/** P0 Smoke — 工作区列表 + 表列表（仅 chromium-authed）. */
import { test, expect } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

async function gotoWorkspace(page: any) {
  await page.goto("/");
  await page.waitForURL(/\/w\/\d+/);
  // 到达 /w/{wid}/tables — TablesList 页面
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

  test("至少有 2 张 seed 表", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // Antd Table 行应该有 2 行（部门表 + 员工表）
    const rows = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect(rows).toHaveCount(2);
  });
});
