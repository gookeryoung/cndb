/** Critical — 复制表后左侧列表立即刷新.
 *
 * 回归修复: GridPage 顶部菜单复制表后只 invalidate 了 `['table', tableKey]`,
 * 没有 invalidate MainLayout Sider 使用的 `['workspaces', wid, 'tables']`,
 * 导致左侧列表需要手动刷新才出现新表。
 */
import { test, expect, APIResponse } from "@playwright/test";

const AUTHS = ["chromium-authed"];

/** 登录获取 token */
async function getToken(request: any): Promise<string> {
  const resp: APIResponse = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  });
  const body = await resp.json();
  return body.access_token;
}

/** 通过 API 删除表（清理用） */
async function deleteTable(request: any, wid: number, tid: number): Promise<void> {
  const token = await getToken(request);
  await request.delete(`/api/v1/workspaces/${wid}/tables/${tid}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
}

/** 获取工作区所有表 */
async function listTables(request: any, wid: number): Promise<any[]> {
  const token = await getToken(request);
  const resp: APIResponse = await request.get(`/api/v1/workspaces/${wid}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return resp.json();
}

/** 进入 GridPage（某张已知存在的表） */
async function gotoGrid(page: any, wid: number, tableName: string) {
  await page.goto(`/w/${wid}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  await page.getByRole("menuitem", { name: new RegExp(tableName) }).click();
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

/** 获取左侧 Sider 的表数量 */
async function getSiderTableCount(page: any): Promise<number> {
  const items = page.locator(".ant-layout-sider .ant-menu .ant-menu-item");
  return await items.count();
}

/** 在 GridPage 点击"更多..." → 执行复制 */
async function clickCopyTable(page: any) {
  // 顶部工具栏的 "MoreOutlined" 按钮 → 打开 Dropdown
  await page.getByRole("button").filter({ has: page.locator(".anticon-more") }).click();
  // 等待 Dropdown 出现
  const dropdown = page.locator(".ant-dropdown-menu");
  await expect(dropdown).toBeVisible();
  // 点击 "复制表"
  await page.getByRole("menuitem", { name: /复制表/ }).click();
}

// ─────────────── 测试 ───────────────

test.describe("复制表回归修复", () => {
  test("GridPage 复制表 → 左侧 Sider 列表立即出现新表", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    const WID = 1;

    // 进入 seed 数据中确定存在的表 "员工表"
    await gotoGrid(page, WID, "员工表");

    // 记录当前 Sider 表数量
    const countBefore = await getSiderTableCount(page);

    // 执行复制
    await clickCopyTable(page);

    // 1. Toast 提示成功
    await expect(page.getByText(/已复制为/)).toBeVisible({ timeout: 5000 });

    // 2. 自动导航到新表 URL（id 变化）
    await page.waitForURL(/\/tables\/\d+/);
    const newUrl = page.url();
    const newTidMatch = newUrl.match(/\/tables\/(\d+)/);
    expect(newTidMatch).not.toBeNull();
    const newTid = Number(newTidMatch![1]);

    // 3. 关键回归验证 — 左侧 Sider 数量立刻 +1
    const countAfter = await getSiderTableCount(page);
    expect(countAfter).toBe(countBefore + 1);

    // 4. Sider 中应该能看到新表（通常命名为 "员工表 (副本)" 或类似）
    // 验证包含 "(副本)" 的 menuitem 出现
    await expect(page.getByRole("menuitem", { name: /副本/ })).toBeVisible({ timeout: 5000 });

    // 5. 清理：通过 API 删除新复制的表
    await deleteTable(request, WID, newTid);

    // 验证清理：刷新后 Sider 数量回到原来的值
    await page.reload();
    await page.waitForURL(/\/tables\/\d+/);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
    const countCleanup = await getSiderTableCount(page);
    expect(countCleanup).toBe(countBefore);
  });
});

test.describe("TablesList 页面复制表（对照 — 不应有回归）", () => {
  test("TablesList 页面复制表 → 列表 +1", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    const WID = 1;

    // 进入 TablesList 页面
    await page.goto(`/w/${WID}/tables`);
    await page.waitForURL(/\/w\/\d+\/tables/);
    await expect(page.getByRole("heading", { level: 3 })).toBeVisible();
    // 等待 Table 数据加载完毕
    await page.waitForSelector(".ant-table-tbody tr.ant-table-row", { state: "visible", timeout: 5000 });

    // 记录当前行数
    const rowsBefore = page.locator(".ant-table-tbody tr.ant-table-row");
    const countBefore = await rowsBefore.count();
    console.log("TablesList rows before:", countBefore);

    // 找到 "员工表" 这行的操作列里的 Dropdown 触发器（Antd 加了 ant-dropdown-trigger class）
    const targetRow = page.getByRole("row", { name: /员工表/ });
    await targetRow.locator(".ant-dropdown-trigger").first().click();

    const dropdown = page.locator(".ant-dropdown-menu");
    await expect(dropdown).toBeVisible();
    await page.getByRole("menuitem", { name: /复制表结构/ }).click();

    // Toast 成功
    await expect(page.getByText(/已复制为/)).toBeVisible({ timeout: 5000 });

    // 列表行数 +1
    const rowsAfter = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect(rowsAfter).toHaveCount(countBefore + 1, { timeout: 5000 });

    // 清理：用 API 删掉新复制的表
    const tables = await listTables(request, WID);
    const source = tables.find((t: any) => t.name === "员工表");
    const copied = tables.find(
      (t: any) => t.id !== source?.id && /员工表/.test(t.name),
    );
    if (copied) {
      await deleteTable(request, WID, copied.id);
    }
  });
});
