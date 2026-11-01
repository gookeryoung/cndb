/** Critical — dashboard 登录态只读分享（ADR 0077 P1 / P2，仅 chromium-authed）.
 *
 * 覆盖：视图栏「复制只读链接」生成的深链 → demo（工作区 VIEWER，被授权 viewer）打开后
 * 进入只读展示（无页面工具栏 / 视图栏 / 编辑入口 / 行详情）；撤权与删除视图后同一链接
 * 显示「链接无效或无权访问」，**不回落默认视图**。
 *
 * 隔离：API 自建唯一命名的 dashboard 视图并复用它跨两个账号，finally 删除。
 */

import { test, expect } from "../fixtures/auth";
import { apiCall, getAdminToken, getTableId, getWorkspaceId, sessionAs } from "../helpers/api";
import {
  DASHBOARD_TABLE_NAME,
  DASHBOARD_WS_NAME,
  createDashboardView,
  deleteView,
  emptyQuery,
  shareViewWithMember,
} from "../helpers/dashboard";

test.describe.configure({ timeout: 120_000 });

/** 只读展示用例的画布：一个明细表（用于验证行点击不打开详情） */
function shareWidgets() {
  return [
    {
      id: "w_rows",
      type: "table",
      title: "订单明细",
      layout: { x: 0, y: 0, w: 12, h: 6 },
      query: emptyQuery(),
      table: { columns: ["订单号"], row_limit: 5 },
    },
  ];
}

/** 打开时替换剪贴板实现，把写入文本留在页面内，避免依赖 headless 的真实剪贴板权限 */
async function captureClipboard(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          (window as unknown as { __copiedLink?: string }).__copiedLink = text;
        },
      },
    });
  });
}

test.describe("dashboard 只读分享", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
    void page;
  });

  test("复制链接 → 只读成员进入展示态；撤权 / 删除后链接失效且不回落", async ({ browser, page, request }) => {
    const wid = await getWorkspaceId(request, DASHBOARD_WS_NAME);
    const tid = await getTableId(request, wid, DASHBOARD_TABLE_NAME);
    const token = await getAdminToken(request);
    const viewName = `P2 只读分享 ${Date.now()}`;

    const viewer = await sessionAs(browser, "demo", "demo1234");
    const view = await createDashboardView(request, token, wid, tid, viewName, {
      schema_version: 1,
      widgets: shareWidgets(),
      global_filters: [],
      settings: { refresh_interval: 0, theme: "inherit" },
    });

    try {
      await shareViewWithMember(request, token, wid, tid, view.id, viewer.userId);

      // admin 打开同一画布，从视图栏「更多」复制只读链接
      await captureClipboard(page);
      await page.goto(`/w/${wid}/tables/${tid}?view=${view.id}&mode=dashboard`);
      await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 10_000 });

      await page.getByTestId("view-more-desktop").click();
      await page.locator(".ant-dropdown-menu-item", { hasText: "复制只读链接" }).click();
      const copied = await page.evaluate(
        () => (window as unknown as { __copiedLink?: string }).__copiedLink ?? "",
      );
      expect(copied, "应复制出只读深链").toBeTruthy();
      expect(copied).toContain(`?view=${view.id}&mode=dashboard&present=1`);

      // 接收者直达链接：只读展示，无页面 chrome 与写入入口
      await viewer.page.goto(copied);
      await expect(viewer.page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 10_000 });
      await expect(viewer.page.getByTestId("dashboard-exit-present")).toBeVisible();
      await expect(viewer.page.getByTestId("import-export-btn")).toHaveCount(0);
      await expect(viewer.page.getByTestId("view-more-desktop")).toHaveCount(0);
      await expect(viewer.page.getByTestId("dashboard-edit")).toHaveCount(0);
      await expect(viewer.page.getByTestId("dashboard-copy-share")).toHaveCount(0);

      // 行点击不打开行详情（唯一可能出现的抽屉是行详情）
      await expect(viewer.page.getByTestId("dashboard-table-row-w_rows-0")).toBeVisible({ timeout: 10_000 });
      await viewer.page.getByTestId("dashboard-table-row-w_rows-0").click();
      await expect(viewer.page.locator(".ant-drawer-open")).toHaveCount(0);

      // 撤权：转回 private → 同一链接显示无效，不回落到默认视图
      const revoked = await apiCall(
        request,
        token,
        "post",
        `/workspaces/${wid}/tables/${tid}/views/${view.id}/visibility`,
        { visibility: "private" },
      );
      expect(revoked.status).toBe(200);

      await viewer.page.goto(copied);
      await expect(viewer.page.getByTestId("dashboard-present-invalid")).toBeVisible({ timeout: 10_000 });
      await expect(viewer.page.getByTestId("dashboard-canvas")).toHaveCount(0);

      // 删除视图后同样失效（不再展示任何画布）
      await deleteView(request, token, wid, tid, view.id);
      await viewer.page.goto(copied);
      await expect(viewer.page.getByTestId("dashboard-present-invalid")).toBeVisible({ timeout: 10_000 });
      await expect(viewer.page.getByTestId("dashboard-canvas")).toHaveCount(0);
    } finally {
      await deleteView(request, token, wid, tid, view.id);
      await viewer.close();
    }
  });
});
