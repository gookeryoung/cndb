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
  test("主应用骨架：顶栏导航 + 二级页签 + 表列表页", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // 需求 0081：数据表 / 文档 / 设计 / 工作区设置一级模块在顶栏导航（C4），
    // 数据分析等二级模块维持在内容区上方页签行（C5）
    await expect(page.getByTestId("ws-nav-tables")).toBeVisible();
    await expect(page.getByTestId("ws-nav-documents")).toBeVisible();
    await expect(page.getByTestId("ws-nav-settings")).toBeVisible();
    await expect(page.getByRole("tab", { name: /数据分析/ })).toBeVisible();

    // 表列表页 — TablesList（用 :has-text 避免匹配到空状态 placeholder row）
    await expect(page.locator('button:has-text("新建表")').first()).toBeVisible();
  });

  test("主页顶栏搜索：进入工作区前可跨工作区搜索并跳转（需求 0081 C3）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await page.goto("/w");
    await page.waitForURL(/\/w$/);

    // 主页模式：无范围选择器，占位口径为全部工作区
    const input = page.getByTestId("global-search-input");
    await expect(input).toBeVisible();
    await expect(page.getByTestId("global-search-scope")).toHaveCount(0);

    // 搜索 seed 数据（某企业销售管理的「电商销售」表），面板出现跨工作区命中
    await input.fill("电商销售");
    const panel = page.getByTestId("global-search-panel");
    await expect(panel).toBeVisible({ timeout: 10_000 });
    await expect(panel).toContainText("范围：全部工作区");
    const hit = panel.getByRole("option").filter({ hasText: "电商销售" }).first();
    await expect(hit).toBeVisible({ timeout: 10_000 });

    // 点击命中进入对应工作区的表
    await hit.click();
    await page.waitForURL(/\/w\/\d+\/tables\/\d+/);
  });

  test("seed 数据：至少有 9 张表（某企业销售管理）", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // WID=1 某企业销售管理有 9 张 seed 表（7 张 CSV 含「产品批次」+ 部门表 + 员工表）
    const rows = page.locator(".ant-table-tbody tr.ant-table-row");
    // 跨文件并行时其它用例可能临时向 WID=1 增表（如权限用例的临时表），
    // 与 grid.spec 同口径：只要求 seed 的 9 张表都在，不锁死精确行数
    await expect.poll(() => rows.count(), { timeout: 10000 }).toBeGreaterThanOrEqual(9);
  });

  test("表列表 owner 列正确展示拥有者用户名", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 项目跳过");
    await gotoWorkspace(page);

    // 等待表列表加载完成
    const rows = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect.poll(() => rows.count(), { timeout: 10000 }).toBeGreaterThanOrEqual(9);

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
