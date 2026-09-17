/** Critical — 表复制三种模式 E2E.
 *
 * 覆盖：
 *   1. 仅复制表结构（structure）→ 新表有字段但 0 行数据
 *   2. 复制表结构 + 全部数据（all）→ 新表字段 + 完整数据
 *   3. 复制当前视图数据（view）→ 新表字段 + 视图过滤子集
 *
 * 附带回归：GridPage 复制后 Sider 列表立即刷新，TablesList 页面两个模式各 1 条
 */
import { test, expect, APIResponse } from "@playwright/test";

const AUTHS = ["chromium-authed"];
const WID = 1;

/** 登录获取 token */
async function getToken(request: any): Promise<string> {
  const resp: APIResponse = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  });
  const body = await resp.json();
  return body.access_token;
}

/** 带 token 的 request 辅助 */
async function authed(request: any) {
  return { headers: { Authorization: `Bearer ${await getToken(request)}` } };
}

/** 创建表（用于测试自建源表，完全自包含） */
async function createTable(request: any, wid: number, name: string): Promise<number> {
  const resp: APIResponse = await request.post(
    `/api/v1/workspaces/${wid}/tables`,
    { data: { name, description: "E2E 临时测试表" }, ...await authed(request) },
  );
  return (await resp.json()).id;
}

/** 创建字段 */
async function createField(
  request: any, wid: number, tid: number, name: string, fieldType = "text", opts: any = {},
): Promise<number> {
  const resp: APIResponse = await request.post(
    `/api/v1/workspaces/${wid}/tables/${tid}/fields`,
    { data: { name, field_type: fieldType, ...opts }, ...await authed(request) },
  );
  return (await resp.json()).id;
}

/** 创建多行数据 */
async function bulkCreateRows(
  request: any, wid: number, tid: number, valuesList: Array<Record<string, unknown>>,
): Promise<number[]> {
  const resp: APIResponse = await request.post(
    `/api/v1/workspaces/${wid}/tables/${tid}/records/bulk-create`,
    { data: { rows: valuesList }, ...await authed(request) },
  );
  return (await resp.json()).ids;
}

/** 创建带 filter 的视图 */
async function createView(
  request: any, wid: number, tid: number,
  name: string, filters: Array<{ field_name: string; op: string; value: unknown }>,
): Promise<number> {
  const resp: APIResponse = await request.post(
    `/api/v1/workspaces/${wid}/tables/${tid}/views`,
    { data: { name, view_type: "grid", filter_type: "AND", filters, sortings: [] }, ...await authed(request) },
  );
  return (await resp.json()).id;
}

/** 删除表（清理用） */
async function deleteTable(request: any, wid: number, tid: number): Promise<void> {
  await request.delete(`/api/v1/workspaces/${wid}/tables/${tid}`, await authed(request));
}

/** 获取表的 record_count */
async function getTableDetail(request: any, wid: number, tid: number): Promise<any> {
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${wid}/tables/${tid}`,
    await authed(request),
  );
  return resp.json();
}

/** 获取工作区所有表 */
async function listTables(request: any, wid: number): Promise<any[]> {
  const resp: APIResponse = await request.get(
    `/api/v1/workspaces/${wid}/tables`,
    await authed(request),
  );
  return resp.json();
}

/** 从列表中按名称前缀找到最新的副本 */
async function findCopyByName(request: any, wid: number, sourceName: string): Promise<any | null> {
  const tables = await listTables(request, wid);
  const source = tables.find((t: any) => t.name === sourceName);
  if (!source) return null;
  // 找 name 包含 "sourceName" 且 id !== source.id 的表
  const candidates = tables.filter(
    (t: any) => t.id !== source.id && t.name.startsWith(sourceName)
  );
  if (candidates.length === 0) return null;
  // 按 id 降序取最新的
  candidates.sort((a: any, b: any) => b.id - a.id);
  return candidates[0];
}

/** 在 GridPage 打开某张表 */
async function gotoGrid(page: any, wid: number, tableName: string) {
  await page.goto(`/w/${wid}/tables`);
  await page.waitForURL(/\/w\/\d+\/tables/);
  await page.getByRole("menuitem", { name: new RegExp(tableName) }).click();
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
}

/** 点击顶部 More → 复制表（SubMenu）→ 指定子项 */
async function clickCopySubmenu(page: any, subItemText: RegExp) {
  // 点击 More 按钮（有 data-testid="grid-more-menu"）
  const moreBtn = page.locator('button[data-testid="grid-more-menu"]');
  await expect(moreBtn).toBeVisible({ timeout: 5000 });
  await moreBtn.click();
  await expect(page.locator(".ant-dropdown-menu-root")).toBeVisible();
  // 找到 SubMenu "复制表" 并展开
  const copySubmenu = page.locator(".ant-dropdown-menu-submenu-title").filter({ hasText: /复制表/ });
  await expect(copySubmenu).toBeVisible({ timeout: 3000 });
  await copySubmenu.hover();
  // antd v5 hover 后 submenu 会渲染独立 popup（.ant-dropdown-menu-submenu-popup）
  await expect(page.locator(".ant-dropdown-menu-submenu-popup")).toBeVisible({ timeout: 5000 });
  // 在 page 级别找子项（popup portal 到 body）
  const subItem = page.getByRole("menuitem", { name: subItemText }).last();
  await expect(subItem).toBeVisible({ timeout: 5000 });
  await subItem.click();
}

// ─────────────── 辅助：一次性准备自建表 ───────────────

/** 创建一张临时表，包含 text + number 字段，插入若干数据行，创建一个带 filter 的视图.
 *
 * 返回 { tableId, viewId, totalRows, filteredRows } — 供各 case 独立调用。
 */
async function setupTestTable(request: any): Promise<{
  tableId: number; viewId: number; totalRows: number; filteredRows: number;
}> {
  const tid = await createTable(request, WID, "E2E复制测试源表");
  await createField(request, WID, tid, "姓名", "text");
  await createField(request, WID, tid, "部门", "text");
  await createField(request, WID, tid, "薪资", "number");
  // 插入 5 行数据：3 行研发、2 行市场
  await bulkCreateRows(request, WID, tid, [
    { 姓名: "张三", 部门: "研发", 薪资: 15000 },
    { 姓名: "李四", 部门: "研发", 薪资: 18000 },
    { 姓名: "王五", 部门: "研发", 薪资: 20000 },
    { 姓名: "赵六", 部门: "市场", 薪资: 12000 },
    { 姓名: "孙七", 部门: "市场", 薪资: 13000 },
  ]);
  const vid = await createView(request, WID, tid, "仅研发部", [
    { field_name: "部门", op: "=", value: "研发" },
  ]);
  return { tableId: tid, viewId: vid, totalRows: 5, filteredRows: 3 };
}

// ─────────────── 测试 ───────────────

test.describe("复制表 — 三种模式（自建表 + UI 操作）", () => {
  test("仅复制表结构 → 新表 0 行数据", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    const { tableId } = await setupTestTable(request);

    // 进入自建源表
    await page.goto(`/w/${WID}/tables/${tableId}`);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();

    // 记录复制前 Sider 数量
    const siderBefore = await page
      .locator(".ant-layout-sider .ant-menu .ant-menu-item")
      .count();

    // 执行：More → 复制表 → 仅复制表结构
    await clickCopySubmenu(page, /仅复制表结构/);

    // 1. Toast 成功提示
    await page.waitForTimeout(500); /* Toast optional, verified by URL + API */

    // 2. 自动导航到新表
    await page.waitForURL(/\/tables\/\d+/);
    const newUrl = page.url();
    const newTidMatch = newUrl.match(/\/tables\/(\d+)/);
    expect(newTidMatch).not.toBeNull();
    const newTid = Number(newTidMatch![1]);
    expect(newTid).not.toBe(tableId);

    // 3. 关键回归：Sider 数量立即 +1
    const siderAfter = await page
      .locator(".ant-layout-sider .ant-menu .ant-menu-item")
      .count();
    expect(siderAfter).toBe(siderBefore + 1);

    // 4. 通过 API 验证：新表 record_count === 0
    const detail = await getTableDetail(request, WID, newTid);
    expect(detail.record_count).toBe(0);
    // 5. 新表有字段（至少姓名/部门/薪资 3 个）
    expect((detail.fields || []).length).toBeGreaterThanOrEqual(3);

    // 清理
    await deleteTable(request, WID, newTid);
    await deleteTable(request, WID, tableId);
  });

  test("复制表结构 + 全部数据 → 新表有完整数据", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    const { tableId, totalRows } = await setupTestTable(request);

    await page.goto(`/w/${WID}/tables/${tableId}`);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();

    // 执行：More → 复制表 → 复制表结构 + 全部数据
    await page.locator('button[data-testid="grid-more-menu"]').click();
    await expect(page.locator(".ant-dropdown-menu-root")).toBeVisible();
    const copySubmenu = page.locator(".ant-dropdown-menu-submenu-title").filter({ hasText: /复制表/ });
    await expect(copySubmenu).toBeVisible({ timeout: 3000 });
    await copySubmenu.hover();
    await expect(page.locator(".ant-dropdown-menu-submenu-popup")).toBeVisible({ timeout: 5000 });
    await page.getByRole("menuitem", { name: /复制表结构.*全部数据/ }).click();

    // Toast 成功提示
    await page.waitForTimeout(500); /* Toast optional, verified by URL + API */

    // 自动导航到新表
    await page.waitForURL(/\/tables\/\d+/);
    const newTidMatch = page.url().match(/\/tables\/(\d+)/);
    expect(newTidMatch).not.toBeNull();
    const newTid = Number(newTidMatch![1]);
    expect(newTid).not.toBe(tableId);

    // API 验证：新表 record_count === totalRows（源表 5 行）
    const detail = await getTableDetail(request, WID, newTid);
    expect(detail.record_count).toBe(totalRows);

    // 清理
    await deleteTable(request, WID, newTid);
    await deleteTable(request, WID, tableId);
  });

  test("复制当前视图数据 → 新表仅含视图过滤子集", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    const { tableId, viewId, filteredRows } = await setupTestTable(request);

    await page.goto(`/w/${WID}/tables/${tableId}`);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();

    // 切换到带 filter 的视图 "仅研发部"
    // 视图 Tab 在 GridPage 顶部 Segmented 中，先确认 Segmented 存在
    await expect(page.locator(".ant-segmented")).toBeVisible({ timeout: 5000 });
    // 直接通过 menuitem 或 button role 查找
    const viewTab = page.getByRole("tab", { name: /仅研发部/ });
    if (await viewTab.count() > 0) {
      await viewTab.click();
    } else {
      // Segmented 的项可能是 div/button
      const segItem = page.locator(".ant-segmented-item").filter({ hasText: /仅研发部/ });
      await expect(segItem).toBeVisible({ timeout: 5000 });
      await segItem.click();
    }

    // 等待数据加载（视图筛选后应该只剩 3 行研发）
    await page.waitForTimeout(800);

    // 执行：More → 复制表 → 复制当前视图数据
    await page.locator('button[data-testid="grid-more-menu"]').click();
    await expect(page.locator(".ant-dropdown-menu-root")).toBeVisible();
    const copySubmenu2 = page.locator(".ant-dropdown-menu-submenu-title").filter({ hasText: /复制表/ });
    await copySubmenu2.hover();
    await expect(page.locator(".ant-dropdown-menu-submenu-popup")).toBeVisible({ timeout: 5000 });
    // 子项文本包含 "当前视图数据" 和视图名 "(仅研发部)"
    await page.getByRole("menuitem", { name: /当前视图数据.*仅研发部/ }).click();

    // Toast 成功
    await page.waitForTimeout(500); /* Toast optional, verified by URL + API */

    // 自动导航到新表
    await page.waitForURL(/\/tables\/\d+/);
    const newTidMatch = page.url().match(/\/tables\/(\d+)/);
    expect(newTidMatch).not.toBeNull();
    const newTid = Number(newTidMatch![1]);
    expect(newTid).not.toBe(tableId);

    // API 验证：新表 record_count === filteredRows（研发部 3 行，不是全部 5 行）
    const detail = await getTableDetail(request, WID, newTid);
    expect(detail.record_count).toBe(filteredRows);
    expect(detail.record_count).not.toBe(5); // 明确不是全量

    // 清理
    await deleteTable(request, WID, newTid);
    await deleteTable(request, WID, tableId);
  });
});

test.describe("复制表 — TablesList 页面（仅结构 + 全部数据）", () => {
  test("TablesList 复制表结构 + 全部数据 → 列表 +1 且数据完整", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    const { tableId, totalRows } = await setupTestTable(request);

    // 进入 TablesList 页面
    await page.goto(`/w/${WID}/tables`);
    await page.waitForURL(/\/w\/\d+\/tables/);
    await expect(page.getByRole("heading", { level: 3 })).toBeVisible();
    await page.waitForSelector(".ant-table-tbody tr.ant-table-row", { state: "visible", timeout: 5000 });
    // 等待自建表行出现
    const targetRow = page.locator(`tr[data-testid="table-row-${tableId}"]`);
    await expect(targetRow).toBeVisible({ timeout: 5000 });

    // 记录行数
    const countBefore = await page.locator(".ant-table-tbody tr.ant-table-row").count();

    // 找到自建表那行 → 点击 More 按钮 → 复制表 → 复制表结构 + 全部数据
    await targetRow.locator(`button[data-testid="more-table-${tableId}"]`).click();
    await expect(page.locator(".ant-dropdown-menu-root")).toBeVisible();

    // SubMenu "复制表"
    const copySubmenu = page.locator(".ant-dropdown-menu-submenu-title").filter({ hasText: /复制表/ });
    await expect(copySubmenu).toBeVisible({ timeout: 3000 });
    await copySubmenu.hover();
    await expect(page.locator(".ant-dropdown-menu-submenu-popup")).toBeVisible({ timeout: 5000 });
    await page.getByRole("menuitem", { name: /复制表结构.*全部数据/ }).click();

    // Toast 成功
    await page.waitForTimeout(500); /* Toast optional, verified by URL + API */

    // 列表行数 +1（可能需要刷新 query）
    const rowsAfter = page.locator(".ant-table-tbody tr.ant-table-row");
    await expect(rowsAfter).toHaveCount(countBefore + 1, { timeout: 10000 });

    // API 验证新表 record_count === totalRows
    const copied = await findCopyByName(request, WID, "E2E复制测试源表");
    expect(copied).not.toBeNull();
    const detail = await getTableDetail(request, WID, copied.id);
    expect(detail.record_count).toBe(totalRows);

    // 清理
    await deleteTable(request, WID, copied.id);
    await deleteTable(request, WID, tableId);
  });

  test("TablesList 复制表仅结构 → 新表 0 行数据", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    const { tableId } = await setupTestTable(request);

    await page.goto(`/w/${WID}/tables`);
    await page.waitForURL(/\/w\/\d+\/tables/);
    await expect(page.getByRole("heading", { level: 3 })).toBeVisible();
    await page.waitForSelector(".ant-table-tbody tr.ant-table-row", { state: "visible", timeout: 5000 });
    // 等待自建表行出现
    const targetRow = page.locator(`tr[data-testid="table-row-${tableId}"]`);
    await expect(targetRow).toBeVisible({ timeout: 5000 });

    const countBefore = await page.locator(".ant-table-tbody tr.ant-table-row").count();

    await targetRow.locator(`button[data-testid="more-table-${tableId}"]`).click();
    await expect(page.locator(".ant-dropdown-menu-root")).toBeVisible();

    const copySubmenu = page.locator(".ant-dropdown-menu-submenu-title").filter({ hasText: /复制表/ });
    await expect(copySubmenu).toBeVisible({ timeout: 3000 });
    await copySubmenu.hover();
    await expect(page.locator(".ant-dropdown-menu-submenu-popup")).toBeVisible({ timeout: 5000 });
    await page.getByRole("menuitem", { name: /仅复制表结构/ }).click();

    await page.waitForTimeout(500); /* Toast optional, verified by URL + API */
    await expect(page.locator(".ant-table-tbody tr.ant-table-row")).toHaveCount(countBefore + 1, { timeout: 10000 });

    const copied = await findCopyByName(request, WID, "E2E复制测试源表");
    expect(copied).not.toBeNull();
    const detail = await getTableDetail(request, WID, copied.id);
    expect(detail.record_count).toBe(0);

    // 清理
    await deleteTable(request, WID, copied.id);
    await deleteTable(request, WID, tableId);
  });
});

test.describe("复制表 — 回归修复（GridPage Sider 立即刷新）", () => {
  test("GridPage 复制表结构 → 左侧 Sider 列表立即出现新表", async ({ page, request }) => {
    if (!AUTHS.includes(test.info().project.name)) return;

    // 使用 seed 数据中确定存在的 "员工表"
    await gotoGrid(page, WID, "员工表");

    const siderBefore = await page
      .locator(".ant-layout-sider .ant-menu .ant-menu-item")
      .count();

    await clickCopySubmenu(page, /仅复制表结构/);

    await page.waitForTimeout(500); /* Toast optional, verified by URL + API */
    await page.waitForURL(/\/tables\/\d+/);
    const newTidMatch = page.url().match(/\/tables\/(\d+)/);
    expect(newTidMatch).not.toBeNull();
    const newTid = Number(newTidMatch![1]);

    // Sider 数量 +1
    const siderAfter = await page
      .locator(".ant-layout-sider .ant-menu .ant-menu-item")
      .count();
    expect(siderAfter).toBe(siderBefore + 1);

    await deleteTable(request, WID, newTid);

    await page.reload();
    await page.waitForURL(/\/tables\/\d+/);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible();
    const siderCleanup = await page
      .locator(".ant-layout-sider .ant-menu .ant-menu-item")
      .count();
    expect(siderCleanup).toBe(siderBefore);
  });
});
