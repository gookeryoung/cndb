/** Critical — 右侧视图类型切换按钮根据数据表 views 动态配置.
 *
 * 背景：GridPage 右上角的模式按钮组（表格/看板/画廊/日历/甘特/WBS）之前硬编码全部 6 个按钮，
 *      无论当前数据表是否拥有对应 view_type 的视图。
 *
 * 本次变更：从 views[] 提取存在的 view_type 集合，仅渲染有对应视图的按钮；
 *          若仅 grid 一种视图类型则整个按钮组隐藏（避免单按钮视觉噪音）.
 *
 * 测试覆盖矩阵（来自 examples/datasets/）:
 *   ┌─ 工作区-某企业销售管理
 *   │   ├─ 部门表          → 仅 grid → 按钮组完全隐藏
 *   │   └─ 产品开发        → grid+kanban+gallery+calendar+gantt → 5 个按钮（缺 wbs）
 *   ├─ 工作区-科研项目管理
 *   │   ├─ 科研项目        → grid+kanban+gallery → 3 个按钮（缺 calendar/gantt/wbs）
 *   │   └─ 项目进展        → grid+kanban+gallery+calendar → 4 个按钮（缺 gantt/wbs）
 *   └─ 工作区-项目管理
 *       └─ WBS任务分解      → grid+kanban+calendar+gantt+wbs → 5 个按钮（缺 gallery）
 */
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";

// ──────────────────────────── 通用辅助 ────────────────────────────

async function getToken(request: APIRequestContext): Promise<string> {
  const resp = await request.post("/api/v1/accounts/auth/login", {
    data: { login: "admin", password: "admin1234" },
  });
  const body = (await resp.json()) as { access_token: string };
  return body.access_token;
}

async function getWorkspaceId(
  request: APIRequestContext,
  nameKeyword?: string,
): Promise<number> {
  const token = await getToken(request);
  const resp = await request.get("/api/v1/workspaces", {
    headers: { Authorization: `Bearer ${token}` },
  });
  const workspaces = (await resp.json()) as Array<{ id: number; name: string }>;
  if (nameKeyword) {
    // 优先精确匹配，fallback 到 includes 匹配（避免 "科研项目管理" 误匹配 "项目管理"）
    const exact = workspaces.find((w) => w.name === nameKeyword);
    if (exact) return exact.id;
    const fuzzy = workspaces.find((w) => w.name.includes(nameKeyword));
    if (fuzzy) return fuzzy.id;
  }
  return workspaces[0].id;
}

async function getTableId(
  request: APIRequestContext,
  wid: number,
  tableName: string,
): Promise<number> {
  const token = await getToken(request);
  const resp = await request.get(`/api/v1/workspaces/${wid}/tables`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const tables = (await resp.json()) as Array<{ id: number; name: string }>;
  const t = tables.find((x) => x.name === tableName);
  if (!t) throw new Error(`未找到表: ${tableName}`);
  return t.id;
}

async function gotoTable(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tableName: string,
) {
  const tid = await getTableId(request, wid, tableName);
  const token = await getToken(request);
  // 清用户激活视图偏好，避免测试间持久化污染
  await request
    .put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    })
    .catch(() => {});

  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({
    timeout: 10000,
  });
  await page.waitForTimeout(1500);
}

async function getApiViewTypes(
  request: APIRequestContext,
  wid: number,
  tid: number,
): Promise<Set<string>> {
  const token = await getToken(request);
  const resp = await request.get(
    `/api/v1/workspaces/${wid}/tables/${tid}/views`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const views = (await resp.json()) as Array<{ view_type: string }>;
  return new Set(views.map((v) => v.view_type));
}

// ──────────────────────────── 按钮组结构断言 ────────────────────────────

/** 断言 Space.Compact 模式按钮组存在且内部按钮数量 === expectedCount */
async function assertModeButtonCount(page: Page, expectedCount: number) {
  const groups = page.locator(".ant-space-compact");
  // 注意：antd Segmented 和 Space.Compact 都是 .ant-space-compact —— 工具栏里有两处用法
  // 我们通过 data-mode 属性过滤，因为 Segmented TAB 按钮没有 data-mode
  const modeBtns = page.locator(".ant-btn[data-mode]");
  if (expectedCount === 0) {
    // 模式按钮组不存在，或者存在但没有 data-mode 按钮
    await expect(modeBtns).toHaveCount(0, { timeout: 3000 });
  } else {
    await expect(modeBtns).toHaveCount(expectedCount, { timeout: 5000 });
  }
}

/** 断言指定模式按钮在 DOM 中存在/不存在 */
async function assertModeButtonExists(
  page: Page,
  mode: string,
  exists: boolean,
) {
  const btn = page.locator(`.ant-btn[data-mode="${mode}"]`);
  if (exists) {
    await expect(btn).toBeVisible({ timeout: 3000 });
  } else {
    await expect(btn).toHaveCount(0);
  }
}

// ──────────────────────────── 测试用例 ────────────────────────────

test.describe("视图类型切换按钮 — 按数据表 views 动态配置", () => {
  const ANON = ["setup", "chromium-anon"];

  test("部门表（仅 grid）→ 模式按钮组完全不渲染", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "企业销售");
    await gotoTable(page, request, wid, "部门表");

    // API 侧确认：只有 grid 视图类型
    const apiTypes = await getApiViewTypes(
      request,
      wid,
      await getTableId(request, wid, "部门表"),
    );
    expect(apiTypes.has("grid")).toBeTruthy();
    expect(apiTypes.size).toBe(1);

    // UI 侧：模式按钮组完全不存在（只有 grid 一种，showModeSwitch=false）
    await assertModeButtonCount(page, 0);
  });

  test("科研项目表（grid+kanban+gallery）→ 显示 3 个按钮，日历/甘特/WBS 按钮不存在", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    await gotoTable(page, request, wid, "科研项目");

    // API 侧确认
    const apiTypes = await getApiViewTypes(
      request,
      wid,
      await getTableId(request, wid, "科研项目"),
    );
    expect(apiTypes.has("grid")).toBeTruthy();
    expect(apiTypes.has("kanban")).toBeTruthy();
    expect(apiTypes.has("gallery")).toBeTruthy();
    expect(apiTypes.has("calendar")).toBeFalsy();
    expect(apiTypes.has("gantt")).toBeFalsy();
    expect(apiTypes.has("wbs")).toBeFalsy();

    // UI 侧
    await assertModeButtonCount(page, 3);
    await assertModeButtonExists(page, "grid", true);
    await assertModeButtonExists(page, "kanban", true);
    await assertModeButtonExists(page, "gallery", true);
    await assertModeButtonExists(page, "calendar", false);
    await assertModeButtonExists(page, "gantt", false);
    await assertModeButtonExists(page, "wbs", false);
  });

  test("项目进展表（grid+kanban+gallery+calendar）→ 显示 4 个按钮，甘特/WBS 按钮不存在", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    await gotoTable(page, request, wid, "项目进展");

    const apiTypes = await getApiViewTypes(
      request,
      wid,
      await getTableId(request, wid, "项目进展"),
    );
    expect(apiTypes.has("grid")).toBeTruthy();
    expect(apiTypes.has("kanban")).toBeTruthy();
    expect(apiTypes.has("gallery")).toBeTruthy();
    expect(apiTypes.has("calendar")).toBeTruthy();
    expect(apiTypes.has("gantt")).toBeFalsy();
    expect(apiTypes.has("wbs")).toBeFalsy();

    await assertModeButtonCount(page, 4);
    await assertModeButtonExists(page, "grid", true);
    await assertModeButtonExists(page, "kanban", true);
    await assertModeButtonExists(page, "gallery", true);
    await assertModeButtonExists(page, "calendar", true);
    await assertModeButtonExists(page, "gantt", false);
    await assertModeButtonExists(page, "wbs", false);
  });

  test("WBS任务分解表（grid+kanban+calendar+gantt+wbs）→ 显示 5 个按钮，画廊按钮不存在", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "项目管理");
    await gotoTable(page, request, wid, "WBS任务分解");

    const apiTypes = await getApiViewTypes(
      request,
      wid,
      await getTableId(request, wid, "WBS任务分解"),
    );
    expect(apiTypes.has("grid")).toBeTruthy();
    expect(apiTypes.has("kanban")).toBeTruthy();
    expect(apiTypes.has("calendar")).toBeTruthy();
    expect(apiTypes.has("gantt")).toBeTruthy();
    expect(apiTypes.has("wbs")).toBeTruthy();
    expect(apiTypes.has("gallery")).toBeFalsy();

    await assertModeButtonCount(page, 5);
    await assertModeButtonExists(page, "grid", true);
    await assertModeButtonExists(page, "kanban", true);
    await assertModeButtonExists(page, "calendar", true);
    await assertModeButtonExists(page, "gantt", true);
    await assertModeButtonExists(page, "wbs", true);
    await assertModeButtonExists(page, "gallery", false);
  });

  test("产品开发表（grid+kanban+gallery+calendar+gantt）→ 显示 5 个按钮（缺 WBS）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "企业销售");
    await gotoTable(page, request, wid, "产品开发");

    const apiTypes = await getApiViewTypes(
      request,
      wid,
      await getTableId(request, wid, "产品开发"),
    );
    expect(apiTypes.has("grid")).toBeTruthy();
    expect(apiTypes.has("kanban")).toBeTruthy();
    expect(apiTypes.has("gallery")).toBeTruthy();
    expect(apiTypes.has("calendar")).toBeTruthy();
    expect(apiTypes.has("gantt")).toBeTruthy();
    expect(apiTypes.has("wbs")).toBeFalsy();

    await assertModeButtonCount(page, 5);
    await assertModeButtonExists(page, "wbs", false);
  });
});

// ──────────────────────────── 切换行为回归 ────────────────────────────

test.describe("动态按钮组 — 点击切换行为回归", () => {
  const ANON = ["setup", "chromium-anon"];

  test("科研项目表点看板按钮 → 切到 kanban 视图；甘特按钮不存在所以不会误渲染", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    await gotoTable(page, request, wid, "科研项目");

    // 只有 3 个按钮
    await assertModeButtonCount(page, 3);

    // 点击看板按钮
    const kanbanBtn = page.locator('.ant-btn[data-mode="kanban"]');
    await kanbanBtn.click();
    await page.waitForTimeout(1000);

    // Segmented 应选中 kanban 类型的视图
    const selectedSeg = page.locator(".ant-segmented-item-selected").first();
    const selectedText = (await selectedSeg.innerText()).trim();
    expect(selectedText).toMatch(/看板/);
  });

  test("WBS任务分解表点 WBS 按钮 → 切到 wbs 视图（画廊按钮不存在不会被误点）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "项目管理");
    await gotoTable(page, request, wid, "WBS任务分解");

    await assertModeButtonCount(page, 5);
    await assertModeButtonExists(page, "gallery", false);
    await assertModeButtonExists(page, "wbs", true);

    const wbsBtn = page.locator('.ant-btn[data-mode="wbs"]');
    await wbsBtn.click();
    await page.waitForTimeout(1200);

    // 渲染了 WBS 视图组件（通过其唯一 DOM 特征）
    await expect(
      page.locator('[data-testid="wbs-view"]'),
    ).toBeVisible({ timeout: 5000 });
  });
});

// ──────────────────────────── 跨表导航切换回归 ────────────────────────────

test.describe("跨表导航 — 模式按钮组跟随数据表 views 变化", () => {
  const ANON = ["setup", "chromium-anon"];

  test("部门表 → 产品开发表 → 科研项目表：按钮组数量动态变化", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "企业销售");

    // 1. 部门表：0 个模式按钮
    await gotoTable(page, request, wid, "部门表");
    await assertModeButtonCount(page, 0);

    // 2. 产品开发表：5 个模式按钮（缺 wbs）
    await gotoTable(page, request, wid, "产品开发");
    await assertModeButtonCount(page, 5);
    await assertModeButtonExists(page, "wbs", false);
    await assertModeButtonExists(page, "gantt", true);

    // 3. 客户流失表：3 个模式按钮（grid+kanban+gallery）
    await gotoTable(page, request, wid, "客户流失");
    await assertModeButtonCount(page, 3);
    await assertModeButtonExists(page, "calendar", false);
    await assertModeButtonExists(page, "gantt", false);
    await assertModeButtonExists(page, "wbs", false);
  });
});
