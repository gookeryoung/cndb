/** Critical — dashboard 整屏导出（ADR 0077 P0 / P2，仅 chromium-authed）.
 *
 * 覆盖：工具栏「导出 PNG / 导出 PDF」产出真实下载且格式正确（PNG / PDF 魔数）；
 * 只读成员（demo，工作区 VIEWER）在展示态仍可导出整屏。
 * 文件名断言（含时间戳与非法字符清洗）由 `dashboardExport.test.ts` 单测覆盖。
 * 隔离：每条用例用 API 自建独立 dashboard 视图（唯一命名）并在 finally 删除。
 */

import { readFileSync } from "node:fs";

import { test, expect } from "../fixtures/auth";
import { getAdminToken, getTableId, getWorkspaceId, sessionAs } from "../helpers/api";
import {
  DASHBOARD_TABLE_NAME,
  DASHBOARD_WS_NAME,
  createDashboardView,
  deleteView,
  emptyQuery,
  openDashboard,
  shareViewWithMember,
} from "../helpers/dashboard";

test.describe.configure({ timeout: 120_000 });

/** 整屏导出用例的最小画布：一个 KPI + 一段说明（覆盖数据组件与纯文本组件） */
function exportWidgets() {
  return [
    {
      id: "w_total",
      type: "kpi",
      title: "订单总数",
      layout: { x: 0, y: 0, w: 4, h: 4 },
      query: emptyQuery(),
      kpi: { value: { field: "订单号", agg: "count" } },
    },
    {
      id: "w_note",
      type: "text",
      title: "导出说明",
      layout: { x: 4, y: 0, w: 8, h: 4 },
      query: emptyQuery(),
      text: { content: "整屏导出：全局筛选栏 + 画布主体" },
    },
  ];
}

function dashboardOptions() {
  return {
    schema_version: 1,
    widgets: exportWidgets(),
    global_filters: [],
    settings: { refresh_interval: 0, theme: "inherit" },
  };
}

/** 触发下载并读出文件内容（路径缺失直接失败，避免「点了但没产出」）
 *
 * 文件名由前端 anchor download 指定且含中文：Chromium 对非 ASCII 文件名的
 * `suggestedFilename` 会回落为 "download"（同 analytics / workspace-backup 用例），
 * 因此这里以落盘内容（PNG / PDF 魔数）为准则，文件名断言放在 `dashboardExport.test.ts`。
 */
async function readDownload(page: import("@playwright/test").Page, action: () => Promise<void>): Promise<Buffer> {
  const downloadPromise = page.waitForEvent("download", { timeout: 60_000 });
  await action();
  const download = await downloadPromise;
  const filePath = await download.path();
  expect(filePath, "下载应落盘到本地路径").toBeTruthy();
  const buf = readFileSync(filePath!);
  expect(buf.length, "导出文件不应为空").toBeGreaterThan(0);
  return buf;
}

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

test.describe("dashboard 整屏导出", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
    void page;
  });

  test("导出 PNG / PDF：产出真实文件且格式正确", async ({ page, request }) => {
    const wid = await getWorkspaceId(request, DASHBOARD_WS_NAME);
    const tid = await getTableId(request, wid, DASHBOARD_TABLE_NAME);
    const token = await getAdminToken(request);
    const stamp = Date.now();
    const viewName = `P2 整屏导出 ${stamp}`;

    const view = await createDashboardView(request, token, wid, tid, viewName, dashboardOptions());

    try {
      await openDashboard(page, wid, tid, view.id);
      await expect(page.getByTestId("dashboard-kpi-value-w_total")).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId("dashboard-export-area")).toBeVisible();

      const png = await readDownload(page, () => page.getByTestId("dashboard-export-png").click());
      expect(png.subarray(0, PNG_MAGIC.length), "PNG 文件头").toEqual(PNG_MAGIC);

      const pdf = await readDownload(page, () => page.getByTestId("dashboard-export-pdf").click());
      expect(pdf.subarray(0, 5).toString("latin1"), "PDF 文件头").toBe("%PDF-");
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("只读成员（无视图编辑权限）在展示态仍可导出 PNG", async ({ browser, request }) => {
    const wid = await getWorkspaceId(request, DASHBOARD_WS_NAME);
    const tid = await getTableId(request, wid, DASHBOARD_TABLE_NAME);
    const token = await getAdminToken(request);
    const viewName = `P2 只读导出 ${Date.now()}`;

    const viewer = await sessionAs(browser, "demo", "demo1234");
    const view = await createDashboardView(request, token, wid, tid, viewName, dashboardOptions());

    try {
      await shareViewWithMember(request, token, wid, tid, view.id, viewer.userId);
      await openDashboard(viewer.page, wid, tid, view.id, { present: true });

      // 展示态：无编辑入口，但刷新 / 导出 / 退出仍在
      await expect(viewer.page.getByTestId("dashboard-edit")).toHaveCount(0);
      await expect(viewer.page.getByTestId("dashboard-export-png")).toBeVisible();
      await expect(viewer.page.getByTestId("dashboard-kpi-value-w_total")).toBeVisible({ timeout: 10_000 });

      const png = await readDownload(viewer.page, () => viewer.page.getByTestId("dashboard-export-png").click());
      expect(png.subarray(0, PNG_MAGIC.length), "只读成员导出同样产出 PNG").toEqual(PNG_MAGIC);
    } finally {
      await deleteView(request, token, wid, tid, view.id);
      await viewer.close();
    }
  });
});
