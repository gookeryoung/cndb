/** Critical — 跨表切换时自动保持视图模式（日历/看板/画廊/表格）.
 *
 * 问题背景：用户在表 A 选中日历视图后，通过侧边栏切换到表 B，
 *           期望自动跳转到表 B 的日历视图（若存在），而不是回到默认 grid。
 *
 * 实现机制：mode 同时持久化到 URL ?mode= 和 localStorage（key: cndb_current_mode），
 *           视图初始化时以 URL view → URL mode → localStorage mode → 用户偏好 → default 的优先级匹配。
 *
 * 精简说明（2026-09）：原 10 条 → 6 条。4 条"表A选X→表B跳X"合并为表驱动；
 *      删"表C切画廊→表A"（与核心场景重复）；URL/刷新/fallback/多循环/用户偏好 保留。
 *
 * 测试数据（科研项目管理工作区，四种视图类型齐全）：
 *   表 A "项目进展":   grid / kanban / gallery / calendar
 *   表 B "科研经费":   grid / kanban / gallery / calendar
 *   表 C "课题负责人": grid / kanban / gallery（无 calendar，fallback 测试）
 */
import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";
import { settle } from "../fixtures/settle";
import { getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";

const ANON = ["setup", "chromium-anon"];

// ── 通用辅助 ──

async function gotoTable(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tableName: string,
  clearPref = true,
) {
  const tid = await getTableId(request, wid, tableName);
  if (clearPref) {
    const token = await getAdminToken(request);
    await request.put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    }).catch(() => { });
  }
  await page.evaluate(() => {
    try { localStorage.removeItem("cndb_current_mode"); } catch { /* 忽略 */ }
  });
  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 10000 });
  await settle(page);
}

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
  await settle(page);
}

function assertUrlHasMode(page: Page, expectedMode: string) {
  const url = new URL(page.url());
  expect(url.searchParams.get("mode")).toBe(expectedMode);
}

async function assertSegmentedSelectedIsType(
  page: Page,
  request: APIRequestContext,
  wid: number,
  tid: number,
  expectedType: string,
) {
  const selected = page.locator(".ant-segmented-item-selected").first();
  const label = (await selected.innerText()).trim();
  const token = await getAdminToken(request);
  const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const views = (await resp.json()) as Array<{ id: number; name: string; view_type: string }>;
  const matched = views.find((v) => v.name === label || label.includes(v.name));
  expect(matched?.view_type).toBe(expectedType);
}

async function clickTableInSidebar(page: Page, tableName: string) {
  const menuItem = page
    .locator(".ant-menu-item")
    .filter({ hasText: tableName });
  await expect(menuItem).toHaveCount(1, { timeout: 5000 });
  await menuItem.first().click();
  await page.waitForURL(/\/tables\/\d+/, { timeout: 10000 });
  await settle(page);
}

// ─────────────── 核心场景：侧边栏导航保持 mode（表驱动） ───────────────

test.describe("跨表切换 — 侧边栏导航自动保持视图模式", () => {
  // (起始mode, 源表, 目标表) 矩阵，覆盖四种视图类型
  const modeMatrix: Array<["grid" | "kanban" | "gallery" | "calendar", string, string]> = [
    ["calendar", "项目进展", "科研经费"],
    ["kanban", "项目进展", "课题负责人"],
    ["gallery", "项目进展", "科研项目"],
    ["grid", "项目进展", "科研经费"],
  ];

  for (const [mode, srcTable, dstTable] of modeMatrix) {
    test(`${srcTable} 切${mode} → 侧边栏 ${dstTable} → 自动跳到 ${mode} 视图`, async ({
      page,
      request,
    }) => {
      test.skip(ANON.includes(test.info().project.name), "anon 跳过");

      const wid = await getWorkspaceId(request, "科研项目管理");

      await gotoTable(page, request, wid, srcTable);
      await clickModeButton(page, mode);
      await assertModeButtonActive(page, mode);

      await clickTableInSidebar(page, dstTable);

      await assertModeButtonActive(page, mode);
      const tidB = await getTableId(request, wid, dstTable);
      await assertSegmentedSelectedIsType(page, request, wid, tidB, mode);
    });
  }
});

// ─────────────── URL 参数场景 ───────────────

test.describe("跨表切换 — URL ?mode= 参数保留（刷新/直接导航）", () => {
  test("直接带 ?mode=calendar 打开表 → 自动跳到日历视图", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "科研经费");

    await page.evaluate(() => {
      try { localStorage.removeItem("cndb_current_mode"); } catch { /* 忽略 */ }
    });

    await page.goto(`/w/${wid}/tables/${tid}?mode=calendar`);
    await page.waitForURL(/\/tables\/\d+\?mode=calendar/);
    await settle(page);

    await assertModeButtonActive(page, "calendar");
    await assertSegmentedSelectedIsType(page, request, wid, tid, "calendar");
  });

  test("表切到日历后刷新页面 → 仍保持日历模式", async ({ page, request }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");

    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "calendar");
    assertUrlHasMode(page, "calendar");

    await page.reload();

    await assertModeButtonActive(page, "calendar");
    assertUrlHasMode(page, "calendar");
  });
});

// ─────────────── 边界：目标表没有对应视图类型 ───────────────

test.describe("跨表切换 — 目标表无匹配视图时 fallback", () => {
  test("表 A 选日历 → 表 C（无日历）→ fallback 到 grid，localStorage mode 保留", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const token = await getAdminToken(request);
    const tidC = await getTableId(request, wid, "课题负责人");

    // 清空表 C 用户偏好，确保走 default 路径
    await request.put(`/api/v1/accounts/preferences/tables/${tidC}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: null },
    }).catch(() => { });

    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "calendar");

    await clickTableInSidebar(page, "课题负责人");

    // localStorage mode=calendar 仍在（持久化成功）
    const storedMode = await page.evaluate(() => localStorage.getItem("cndb_current_mode"));
    expect(storedMode).toBe("calendar");

    // 但表 C 渲染的视图类型应为 grid（fallback）
    await assertSegmentedSelectedIsType(page, request, wid, tidC, "grid");
    await assertModeButtonActive(page, "grid");
  });
});

// ─────────────── 多轮循环：跨多张表保持同一模式 ───────────────

test.describe("跨表切换 — 多表循环保持同一模式", () => {
  test("日历模式依次切换 4 张表 → 有 calendar 的表自动跳到日历", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const token = await getAdminToken(request);

    const tidProg = await getTableId(request, wid, "项目进展");
    const tidFund = await getTableId(request, wid, "科研经费");
    const tidProj = await getTableId(request, wid, "科研项目");

    const getViewTypes = async (tid: number): Promise<Set<string>> => {
      const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const views = (await resp.json()) as Array<{ view_type: string }>;
      return new Set(views.map((v) => v.view_type));
    };

    await gotoTable(page, request, wid, "项目进展");
    await clickModeButton(page, "calendar");
    await assertModeButtonActive(page, "calendar");

    // 科研经费（有 calendar）
    await clickTableInSidebar(page, "科研经费");
    if ((await getViewTypes(tidFund)).has("calendar")) {
      await assertModeButtonActive(page, "calendar");
    }

    // 科研项目（无 calendar）→ fallback，localStorage mode 保留
    await clickTableInSidebar(page, "科研项目");
    if (!(await getViewTypes(tidProj)).has("calendar")) {
      const stored = await page.evaluate(() => localStorage.getItem("cndb_current_mode"));
      expect(stored).toBe("calendar");
    }

    // 回到科研经费 → 再次自动跳到日历
    await clickTableInSidebar(page, "科研经费");
    if ((await getViewTypes(tidFund)).has("calendar")) {
      await assertModeButtonActive(page, "calendar");
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
    const token = await getAdminToken(request);
    const tidProg = await getTableId(request, wid, "项目进展");

    // 为"项目进展"表设置一个 kanban 的 active_view_id
    const viewsResp = await request.get(`/api/v1/workspaces/${wid}/tables/${tidProg}/views`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await viewsResp.json()) as Array<{ id: number; view_type: string }>;
    const kanbanView = views.find((v) => v.view_type === "kanban");
    expect(kanbanView).toBeTruthy();

    await request.put(`/api/v1/accounts/preferences/tables/${tidProg}/active-view`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { active_view_id: kanbanView!.id },
    });

    await page.evaluate(() => {
      try { localStorage.removeItem("cndb_current_mode"); } catch { /* 忽略 */ }
    });

    await page.goto(`/w/${wid}/tables/${tidProg}`);
    await page.waitForURL(/\/tables\/\d+/);

    await assertModeButtonActive(page, "kanban");
    await assertSegmentedSelectedIsType(page, request, wid, tidProg, "kanban");
  });
});
