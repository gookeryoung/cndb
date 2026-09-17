/** P0 Smoke — 工作区列表 + 表列表（仅 chromium-authed）. */
import { test, expect } from "../fixtures/auth";

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
    await expect(page.getByRole("button", { name: /回收站/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /报表/ })).toBeVisible();

    // 表列表页 — TablesList（用 :has-text 避免匹配到空状态 placeholder row）
    await expect(page.locator('button:has-text("新建表")').first()).toBeVisible();
  });

  test("seed 数据：至少有 6 张表（某企业销售管理）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // WID=1 某企业销售管理有 6 张 seed 表
    const rows = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect(rows).toHaveCount(6);
  });

  test("表列表 owner 列正确展示拥有者用户名", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // 等待表列表加载完成
    const rows = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect(rows).toHaveCount(6);

    // 表头应包含「拥有者」列
    await expect(page.locator("th", { hasText: "拥有者" }).first()).toBeVisible();

    // 每一行的拥有者列不应是空（seed 表都有 owner=admin）
    // 取第一行的 owner cell（TablesList 列顺序：drag | 表名 | 描述 | 拥有者 | ...，所以 owner 在第 4 列即 nth(3)）
    const firstRowOwnerCell = rows.first().locator("td").nth(3);
    await expect(firstRowOwnerCell).toBeVisible();
    // 应该显示 admin（而不是"未指定"）
    await expect(firstRowOwnerCell).not.toHaveText("未指定");
    await expect(firstRowOwnerCell).toContainText("admin");
  });
});
