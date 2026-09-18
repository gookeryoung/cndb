/** Critical — 右侧 ButtonGroup ↔ 左侧 Segmented TAB 双向联动.
 *
 * 问题背景：GridPage 顶部有两套视图控件：
 *   - Segmented TAB（左侧）: 显示后端视图列表
 *   - ButtonGroup（右侧）: 模式按钮（表格/看板/画廊/日历）
 *
 * 期望双向联动：
 *   方向 A: Segmented 点选某视图 → loadView 根据 view_type 自动同步 ButtonGroup 高亮
 *   方向 B: ButtonGroup 点击某模式 → 跳到第一个匹配 view_type 的视图 → Segmented 选中项同步变化
 *
 * 精简说明（2026-09）：原 9 条 → 4 条。方向 B 4 条 + 方向 A 2 条合并为表驱动循环；
 *      循环切换/幂等/废弃警告 保留（独立价值）。
 *
 * 测试数据："项目进展"表（科研项目管理工作区）四种视图类型齐全。
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
) {
  const tid = await getTableId(request, wid, tableName);
  const token = await getAdminToken(request);
  await request.put(`/api/v1/accounts/preferences/tables/${tid}/active-view`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { active_view_id: null },
  }).catch(() => { });

  await page.goto(`/w/${wid}/tables/${tid}`);
  await page.waitForURL(/\/tables\/\d+/);
  await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 10000 });
  await settle(page);
}

async function activateView(page: Page, viewId: number) {
  const url = new URL(page.url());
  url.searchParams.set("view", String(viewId));
  await page.goto(url.toString());
  await settle(page);
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

// ─────────────── 方向 B：ButtonGroup → Segmented 联动（表驱动） ───────────────

test.describe("双向联动 — 方向 B：ButtonGroup 点击 → Segmented 选中项跳到匹配视图", () => {
  const modes: Array<"kanban" | "gallery" | "calendar" | "grid"> = [
    "kanban",
    "gallery",
    "calendar",
    "grid",
  ];

  for (const mode of modes) {
    test(`点 ${mode} 按钮 → Segmented 跳到第一个 ${mode} 视图`, async ({ page, request }) => {
      test.skip(ANON.includes(test.info().project.name), "anon 跳过");

      const wid = await getWorkspaceId(request, "科研项目管理");
      const tid = await getTableId(request, wid, "项目进展");

      await gotoTable(page, request, wid, "项目进展");
      await clickModeButton(page, mode);

      await assertSegmentedSelectedIsType(page, request, wid, tid, mode);
      await assertModeButtonActive(page, mode);
    });
  }
});

// ─────────────── 方向 A：Segmented → ButtonGroup 同步（回归） ───────────────

test.describe("双向联动 — 方向 A：Segmented 点击 → ButtonGroup 模式同步", () => {
  const modes: Array<"kanban" | "gallery"> = ["kanban", "gallery"];

  for (const mode of modes) {
    test(`Segmented 点 ${mode} 视图 → ButtonGroup ${mode} 按钮高亮`, async ({ page, request }) => {
      test.skip(ANON.includes(test.info().project.name), "anon 跳过");

      const wid = await getWorkspaceId(request, "科研项目管理");
      const tid = await getTableId(request, wid, "项目进展");
      const token = await getAdminToken(request);
      const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const views = (await resp.json()) as Array<{ id: number; name: string; view_type: string }>;
      const targetView = views.find((v) => v.view_type === mode);
      if (!targetView) test.skip(`无 ${mode} 视图`);

      await gotoTable(page, request, wid, "项目进展");
      await activateView(page, targetView!.id);

      await assertModeButtonActive(page, mode);
    });
  }
});

// ─────────────── 循环切换与幂等 ───────────────

test.describe("双向联动 — 循环切换与幂等", () => {
  test("按 ButtonGroup 四种模式依次切换 → Segmented 选中项循环匹配", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");

    await gotoTable(page, request, wid, "项目进展");

    const cycle: Array<"kanban" | "gallery" | "calendar" | "grid"> = [
      "kanban",
      "gallery",
      "calendar",
      "grid",
    ];
    for (const m of cycle) {
      await clickModeButton(page, m);
      await assertSegmentedSelectedIsType(page, request, wid, tid, m);
      await assertModeButtonActive(page, m);
    }
  });

  test("当前视图已是目标类型 → 连续点同一按钮不触发跳转（幂等）", async ({
    page,
    request,
  }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const wid = await getWorkspaceId(request, "科研项目管理");
    const tid = await getTableId(request, wid, "项目进展");
    const token = await getAdminToken(request);
    const resp = await request.get(`/api/v1/workspaces/${wid}/tables/${tid}/views`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const views = (await resp.json()) as Array<{ id: number; view_type: string }>;
    const kanbanView = views.find((v) => v.view_type === "kanban");
    if (!kanbanView) test.skip("无看板视图");

    await gotoTable(page, request, wid, "项目进展");
    await activateView(page, kanbanView.id);
    await assertModeButtonActive(page, "kanban");

    const before = page.url();
    for (let i = 0; i < 3; i++) {
      await clickModeButton(page, "kanban");
    }
    expect(page.url()).toBe(before);
    await assertSegmentedSelectedIsType(page, request, wid, tid, "kanban");
  });
});

// ─────────────── 回归：Button.Group 废弃警告已消除 ───────────────

test.describe("废弃 API 清理 — Button.Group 警告", () => {
  test("GridPage + CalendarView 页面打开时无 Button.Group 控制台警告", async ({ page }) => {
    test.skip(ANON.includes(test.info().project.name), "anon 跳过");

    const warnings: string[] = [];
    page.on("console", (msg) => {
      if (
        msg.type() === "warning" &&
        msg.text().includes("Button.Group")
      ) {
        warnings.push(msg.text());
      }
    });

    await page.goto(`/w/1/tables/1`);
    await expect(page.getByRole("button", { name: /新增行/ })).toBeVisible({ timeout: 10000 });

    const calendarBtn = page.locator('.ant-space-compact button:has(.anticon-calendar)');
    if ((await calendarBtn.count()) > 0) {
      await calendarBtn.click();
      await settle(page);
    }

    expect(warnings, `发现 Button.Group 废弃警告: ${warnings.join(" | ")}`).toHaveLength(0);
  });
});
