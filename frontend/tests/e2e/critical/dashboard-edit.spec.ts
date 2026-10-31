/** Critical — dashboard 画布编辑（ADR 0023 P1，仅 chromium-authed）.
 *
 * 覆盖：进入编辑态 → 拖动标题栏让 KPI 右移一格 → 显式保存 → 后端持久化新坐标。
 * 清理：用例结束把「销售画布」的 view_options 还原为 seed 原值，避免污染其他 spec。
 */

import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";
import { apiCall, getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";

const WS_NAME = "某企业销售管理";
const TABLE_NAME = "电商销售";
const VIEW_NAME = "销售画布";
const WIDGET_ID = "w_orders";

interface ViewItem {
  id: number;
  name: string;
  view_type: string;
  view_options: Record<string, unknown> | null;
}

interface DashboardOptions {
  widgets?: Array<{ id: string; layout: { x: number; y: number; w: number; h: number } }>;
  [key: string]: unknown;
}

async function listViews(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
): Promise<ViewItem[]> {
  const res = await apiCall(request, token, "get", `/workspaces/${wid}/tables/${tid}/views`);
  if (res.status !== 200) throw new Error(`读取视图失败：${res.status}`);
  return res.body as ViewItem[];
}

/** 打开销售画布视图并等待画布就绪 */
async function openDashboard(page: Page, wid: number, tid: number) {
  await page.goto(`/w/${wid}/tables/${tid}`);
  const tab = page.locator('[data-testid^="view-tab-"]', { hasText: VIEW_NAME });
  await expect(tab).toBeVisible({ timeout: 10000 });
  await tab.click();
  await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 10000 });
}

test.describe("dashboard 画布编辑", () => {
  test("拖拽 KPI 后保存，坐标持久化", async ({ page, request }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");

    const wid = await getWorkspaceId(request, WS_NAME);
    const tid = await getTableId(request, wid, TABLE_NAME);
    const token = await getAdminToken(request);
    const views = await listViews(request, token, wid, tid);
    const view = views.find((v) => v.view_type === "dashboard" && v.name === VIEW_NAME);
    expect(view, `未找到 seed 视图：${VIEW_NAME}`).toBeTruthy();
    const original = view!.view_options as DashboardOptions;
    const vid = view!.id;

    try {
      await openDashboard(page, wid, tid);

      await page.getByTestId("dashboard-edit").click();
      await expect(page.getByTestId("dashboard-save")).toBeVisible();
      await expect(page.getByTestId("dashboard-edit-hint")).toBeVisible();

      // 计算单列宽度与行距（与 DashboardGrid.gridMetrics 同口径）
      const canvas = page.getByTestId("dashboard-canvas");
      const canvasBox = (await canvas.boundingBox())!;
      const padding = 16;
      const gap = 12;
      const rowHeight = 40;
      const colWidth = (canvasBox.width - padding * 2 - gap * 11) / 12;

      const handle = page.getByTestId(`dashboard-widget-${WIDGET_ID}-drag-handle`);
      await expect(handle).toBeVisible();
      const hb = (await handle.boundingBox())!;
      const startX = hb.x + hb.width / 2;
      const startY = hb.y + hb.height / 2;
      await page.mouse.move(startX, startY);
      await page.mouse.down();
      // 先小幅移动越过 4px 激活阈值，再移到目标格
      await page.mouse.move(startX + 8, startY, { steps: 3 });
      await page.waitForTimeout(120);
      await page.mouse.move(startX + colWidth, startY + rowHeight + gap, { steps: 20 });
      await page.waitForTimeout(120);
      await page.mouse.up();
      // 拖拽提交进入撤销栈（撤销按钮由禁用翻为可用）
      await expect(page.getByTestId("dashboard-undo")).toBeEnabled();
      // dnd-kit 在拖拽激活后于 document 捕获阶段拦截 click，松手 50ms 后才移除；
      // 立即点击工具栏会被吞掉（mousedown 仍获得焦点），故等过该窗口再保存
      await page.waitForTimeout(300);

      const saveResp = page.waitForResponse(
        (r) => r.request().method() === "PATCH" && r.url().includes(`/views/${vid}`),
        { timeout: 10000 },
      );
      await page.getByTestId("dashboard-save").click();
      await saveResp;
      await expect(page.getByTestId("dashboard-edit")).toBeVisible();

      // 后端已持久化新坐标（右侧一格）
      await expect
        .poll(async () => {
          const latest = (await listViews(request, token, wid, tid)).find((v) => v.id === vid);
          const widget = (latest?.view_options as DashboardOptions | null)?.widgets?.find((w) => w.id === WIDGET_ID);
          return widget?.layout.x;
        }, { timeout: 10000 })
        .toBe(1);

      // 重新加载后画布仍按新坐标渲染（编辑入口可再次进入）
      await openDashboard(page, wid, tid);
      await expect(page.getByTestId("dashboard-card-" + WIDGET_ID)).toBeVisible();
    } finally {
      await apiCall(request, token, "patch", `/workspaces/${wid}/tables/${tid}/views/${vid}`, {
        view_options: original,
      });
    }
  });
});
