/** Critical — 跨表切换时自动保持视图模式（日历/看板/画廊/表格）.
 *
 * 问题背景：用户在表 A 选中日历视图后，通过侧边栏切换到表 B，
 *           期望自动跳转到表 B 的日历视图（若存在），而不是回到默认 grid。
 *
 * 实现机制：mode 同时持久化到 URL ?mode= 和 localStorage（key: cndb_current_mode），
 *           视图初始化时以 URL view → URL mode → localStorage mode → 用户偏好 → default 的优先级匹配。
 *
 * 测试数据（科研项目管理工作区，四种视图类型齐全）：
 *   表 A "项目进展":   grid / kanban / gallery / calendar（"进展日历"）
 *   表 B "科研经费":   grid / kanban / gallery / calendar（"拨付日历"）
 *   表 C "课题负责人": grid / kanban / gallery（无 calendar，fallback 测试）
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";

const ANON = ["setup", "chromium-anon"];

// ── 通用辅助（与 view-mode-sync.spec.ts 保持一致） ──

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
    const ws = workspaces.find((w) => w.name === nameKeyword) || workspaces.find((w) => w.name.includes(nameKeyword));
    if (ws) return ws.id;
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
  clearPref = true,
) {
  const tid = await getTableId(request, wid, tableName);
  if (clearPref) {
    // 清用户激活视图偏好，避免上一个测试的持久化状态污染
    const token = await getToken(request);
    await request.put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    }).catch(() => { });
  }
  // 清 localStorage 里的 mode，确保每个测试从干净状态开始
  await page.evaluate(() => {
    try { localStorage.removeItem("cndb_current_mode"); } catch { /* 忽略 */ }
  });
  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".ant-space-compact")).toHaveCount(1, { timeout: 10000 });
  await page.waitForTimeout(1500);
}

/** 断言 ButtonGroup 指定模式按钮为 primary（高亮）. */
async function assertModeButtonActive(page: Page, mode: "grid" | "kanban" | "gallery" | "calendar") {
  const iconClassMap: Record<string, string> = {
    grid: "anticon-column-height",
    kanban: "anticon-appstore",
    gallery: "anticon-eye",
    calendar: "anticon-calendar",
  };
  const btn = page.locator(`.ant-space-compact button:has(.${iconClassMap[mode]})`);
  await expect(btn).toHaveCount(1, { timeout: 3000 });
  await expect(btn).toHaveClass(/ant-btn-primary/);
}

/** 点击 ButtonGroup 指定模式按钮 */
async function clickModeButton(page: Page, mode: "grid" | "kanban" | "gallery" | "calendar") {
  const iconClassMap: Record<string, string> = {
    grid: "anticon-column-height",
    kanban: "anticon-appstore",
    gallery: "anticon-eye",
    calendar: "anticon-calendar",
  };
  const btn = page.locator(`.ant-space-compact button:has(.${iconClassMap[mode]})`);
  await expect(btn).toHaveCount(1, { timeout: 3000 });
  await btn.click();
  await page.waitForTimeout(1000);
}

/** 断言 URL 包含 mode= 参数且值匹配目标模式 */
function assertUrlHasMode(page: Page, expectedMode: string) {
  const url = new URL(page.url());
  expect(url.searchParams.get("mode")).toBe(expectedMode);
}

/** 断言 Segmented 选中项的 view_type 匹配目标类型（通过 API 查） */
async function assertSegmentedSelectedIsType(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tid: number,
  expectedType: string,
) {
  const selected = page.locator(".ant-segmented-item-selected").first();
  const label = (await selected.innerText()).trim();

  const token = await getToken(request);
  const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const views = (await resp.json()) as Array<{ id: number; name: string; view_type: string }>;
  const matched = views.find((v) => v.name === label || label.includes(v.name));
  expect(matched, `Segmented 选中项 "${label}" 未在视图列表中找到`).toBeTruthy();
  expect(matched!.view_type).toBe(expectedType);
}

/** 通过侧边栏 Menu 点击目标表名（当前工作区内的表） */
async function clickTableInSidebar(page: Page, tableName: string) {
  // 侧边栏 Menu item 的 label 就是表名
  const menuItem = page
    .locator(".ant-menu-item")
    .filter({ hasText: tableName });
  await expect(menuItem).toHaveCount(1, { timeout: 5000 });
  await menuItem.first().click();
  await page.waitForURL(/\/tables\/\d+/, { timeout: 10000 });
  await page.waitForTimeout(1200);
}

// ─────────────── 核心场景：侧边栏导航保持 mode ───────────────

test.describe("跨表切换 — 侧边栏导航自动保持视图模式", () => {
  test("表 A 选日历 → 点侧边栏表 B → 自动跳到表 B 的日历视图", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");

    // 1. 进入表 A（项目进展）
    await gotoTable(page, request, wid, "项目进展");

    // 2. 切到日历模式
    await clickModeButton(page, "calendar");
    await assertModeButtonActive(page, "calendar");
    assertUrlHasMode(page, "calendar");

    // 3. 通过侧边栏导航到表 B（科研经费）—— 表 B 也有日历视图
    await clickTableInSidebar(page, "科研经费");

    // 4. 断言：表 B 自动跳到日历视图（"拨付日历"）
    await assertModeButtonActive(page, "calendar");
    assertUrlHasMode(page, "calendar");
    const tidB = await getTableId(request, wid, "科研经费");
    await assertSegmentedSelectedIsType(page, request, wid, tidB, "calendar");
  });

  test("表 A 选看板 → 点侧边栏表 B → 自动跳到表 B 的看板视图", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");

    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "kanban");
    await assertModeButtonActive(page, "kanban");

    await clickTableInSidebar(page, "课题负责人");

    await assertModeButtonActive(page, "kanban");
    const tidB = await getTableId(request, wid, "课题负责人");
    await assertSegmentedSelectedIsType(page, request, wid, tidB, "kanban");
  });

  test("表 A 选画廊 → 点侧边栏表 B → 自动跳到表 B 的画廊视图", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");

    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "gallery");
    await assertModeButtonActive(page, "gallery");

    await clickTableInSidebar(page, "科研项目");

    await assertModeButtonActive(page, "gallery");
    const tidB = await getTableId(request, wid, "科研项目");
    await assertSegmentedSelectedIsType(page, request, wid, tidB, "gallery");
  });

  test("表 A 选表格 → 点侧边栏表 B → 自动跳到表 B 的 grid 视图（默认）", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");

    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "grid");
    await assertModeButtonActive(page, "grid");

    await clickTableInSidebar(page, "科研经费");

    await assertModeButtonActive(page, "grid");
    const tidB = await getTableId(request, wid, "科研经费");
    await assertSegmentedSelectedIsType(page, request, wid, tidB, "grid");
  });
});

// ─────────────── URL 参数场景 ───────────────

test.describe("跨表切换 — URL ?mode= 参数保留（刷新/直接导航）", () => {
  test("直接带 ?mode=calendar 打开表 B → 自动跳到日历视图", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "科研经费");

    // 清 localStorage
    await page.evaluate(() => {
      try { localStorage.removeItem("cndb_current_mode"); } catch { /* 忽略 */ }
    });

    // 直接用 URL 带 mode=calendar 打开
    await page.goto(`/w/${wid}/tables/${tid}?mode=calendar`);
    await page.waitForURL(/\/tables\/\d+\?mode=calendar/);
    await page.waitForTimeout(2000);

    await assertModeButtonActive(page, "calendar");
    await assertSegmentedSelectedIsType(page, request, wid, tid, "calendar");
  });

  test("表 A 切到日历后刷新页面 → 仍保持日历模式", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");

    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "calendar");
    await assertModeButtonActive(page, "calendar");
    assertUrlHasMode(page, "calendar");

    // 刷新页面
    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1500);

    // 刷新后 mode 应保留
    await assertModeButtonActive(page, "calendar");
    assertUrlHasMode(page, "calendar");
  });
});

// ─────────────── 边界：目标表没有对应视图类型 ───────────────

test.describe("跨表切换 — 目标表无匹配视图时的 fallback", () => {
  test("表 A 选日历 → 点侧边栏表 C（无日历视图）→ fallback 到 default/第一个视图", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const token = await getToken(request);
    const tidC = await getTableId(request, wid, "课题负责人");

    // 预先清空表 C 的用户偏好，避免残留状态干扰 fallback 路径
    await request.put(`/api/v1/accounts/preferences/tables/${tidC}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    }).catch(() => { });

    // 1. 表 A（项目进展）有日历视图 → 切到日历
    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "calendar");
    await assertModeButtonActive(page, "calendar");

    // 2. 导航到表 C（课题负责人）—— 该表**没有** calendar 视图
    await clickTableInSidebar(page, "课题负责人");

    // 3. 断言：mode 持久化到了 localStorage，但表 C 找不到 calendar 视图
    //    此时应 fallback 到 default / 第一个视图（按初始化优先级）
    //    由于已清空用户偏好、URL 无 view 参数，应走 default 或第一个
    // 验证 localStorage 里 mode=calendar 仍在（持久化成功）
    const storedMode = await page.evaluate(() => {
      try { return localStorage.getItem("cndb_current_mode"); } catch { return null; }
    });
    expect(storedMode).toBe("calendar");

    // 但表 C 渲染的视图类型不应是 calendar（因为表 C 根本没有 calendar 视图）
    // 它应该 fallback 到 default（课题负责人的 default 是 grid "全部"）
    const selected = page.locator(".ant-segmented-item-selected").first();
    const label = (await selected.innerText()).trim();
    const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tidC}/views`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await resp.json()) as Array<{ id: number; name: string; view_type: string }>;
    const matched = views.find((v) => v.name === label || label.includes(v.name));
    expect(matched?.view_type).not.toBe("calendar");
    // 期望 fallback 到 grid（default 视图类型）
    expect(matched?.view_type).toBe("grid");
    // ButtonGroup 也应高亮 grid（因为 loadView 根据 view_type 设置 mode）
    await assertModeButtonActive(page, "grid");
  });

  test("表 C 切到画廊后 → 点侧边栏表 A → 自动跳到画廊视图（画廊视图表间都有）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");

    // 表 C（课题负责人）有 gallery 视图 → 切到画廊
    await gotoTable(page, request, wid, "课题负责人");
    await clickModeButton(page, "gallery");
    await assertModeButtonActive(page, "gallery");

    // 导航到表 A（项目进展）—— 也有 gallery 视图
    await clickTableInSidebar(page, "项目进展");

    await assertModeButtonActive(page, "gallery");
    const tidA = await getTableId(request, wid, "项目进展");
    await assertSegmentedSelectedIsType(page, request, wid, tidA, "gallery");
  });
});

// ─────────────── 多轮循环：跨多张表保持同一模式 ───────────────

test.describe("跨表切换 — 多表循环保持同一模式", () => {
  test("日历模式依次切换 4 张表 → 每张有 calendar 的表都自动跳到日历视图", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const token = await getToken(request);

    // 先拿到各表 tid
    const tidProg = await getTableId(request, wid, "项目进展");
    const tidFund = await getTableId(request, wid, "科研经费");
    const tidProj = await getTableId(request, wid, "科研项目");
    const tidChief = await getTableId(request, wid, "课题负责人");

    // 每张表的视图类型清单
    const getViewTypes = async (tid: number): Promise<Set<string>> => {
      const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const views = (await resp.json()) as Array<{ view_type: string }>;
      return new Set(views.map((v) => v.view_type));
    };

    // 1. 入口：项目进展（有 calendar）→ 切日历
    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "calendar");
    await assertModeButtonActive(page, "calendar");

    // 2. 科研经费（有 calendar）→ 应自动跳到日历
    await clickTableInSidebar(page, "科研经费");
    const fundTypes = await getViewTypes(tidFund);
    if (fundTypes.has("calendar")) {
      await assertModeButtonActive(page, "calendar");
      await assertSegmentedSelectedIsType(page, request, wid, tidFund, "calendar");
    }

    // 3. 科研项目（无 calendar）→ fallback 到 default，但 localStorage mode 保留
    await clickTableInSidebar(page, "科研项目");
    const projTypes = await getViewTypes(tidProj);
    if (!projTypes.has("calendar")) {
      // 不在此断言具体 fallback 类型，只验证 localStorage mode 仍为 calendar
      const stored = await page.evaluate(() => localStorage.getItem("cndb_current_mode"));
      expect(stored).toBe("calendar");
    }

    // 4. 课题负责人（无 calendar）→ 同上 fallback
    await clickTableInSidebar(page, "课题负责人");
    const chiefTypes = await getViewTypes(tidChief);
    if (!chiefTypes.has("calendar")) {
      const stored = await page.evaluate(() => localStorage.getItem("cndb_current_mode"));
      expect(stored).toBe("calendar");
    }

    // 5. 回到科研经费 → 应再次自动跳到日历（localStorage mode 被保留了）
    await clickTableInSidebar(page, "科研经费");
    if (fundTypes.has("calendar")) {
      await assertModeButtonActive(page, "calendar");
      await assertSegmentedSelectedIsType(page, request, wid, tidFund, "calendar");
    }

    // 6. 回到项目进展 → 再次自动跳到日历
    await clickTableInSidebar(page, "项目进展");
    const progTypes = await getViewTypes(tidProg);
    if (progTypes.has("calendar")) {
      await assertModeButtonActive(page, "calendar");
      await assertSegmentedSelectedIsType(page, request, wid, tidProg, "calendar");
    }
  });
});

// ─────────────── 回归：旧有的 per-table active_view_id 偏好仍正常工作 ───────────────

test.describe("回归 — per-table active_view_id 用户偏好不被破坏", () => {
  test("没有 localStorage mode / URL mode 时，仍按用户偏好加载视图", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const token = await getToken(request);

    // 先为"项目进展"表设置一个特定的 active_view_id（不是 default，是一个 kanban 视图）
    const tidProg = await getTableId(request, wid, "项目进展");
    const viewsResp = await request.get(`/api/v1/workspaces/${wid}/tables/${tidProg}/views`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await viewsResp.json()) as Array<{ id: number; view_type: string }>;
    const kanbanView = views.find((v) => v.view_type === "kanban");
    expect(kanbanView).toBeTruthy();

    // 设置用户偏好
    await request.put(`/api/v1/accounts/preferences/tables/${tidProg}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: kanbanView!.id },
    });

    // 清 localStorage + 不带 URL 参数打开
    await page.evaluate(() => {
      try { localStorage.removeItem("cndb_current_mode"); } catch { /* 忽略 */ }
    });

    await page.goto(`/w/${wid}/tables/${tidProg}`);
    await page.waitForURL(/\/tables\/\d+/);
    await page.waitForTimeout(2500); // 用户偏好查询 + 加载需要等待

    // 应该加载了 kanban 视图（用户偏好）
    await assertModeButtonActive(page, "kanban");
    await assertSegmentedSelectedIsType(page, request, wid, tidProg, "kanban");
  });
});
