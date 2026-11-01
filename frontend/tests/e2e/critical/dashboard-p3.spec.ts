/** Critical — dashboard 画布 P3 能力（ADR 0023 P3，仅 chromium-authed）.
 *
 * 覆盖：模板另存 → 从模板创建的同表往返 · 跨表数据来源切换与服务端取数 ·
 * `{{global.x}}` 全局筛选联动（未应用标记 / 清除）· `refresh_interval` 定时刷新 ·
 * 模板缺字段映射改写字段后保存。
 *
 * 隔离策略：每条用例用 API 自建独立 dashboard 视图（唯一命名）并在 finally 删除，
 * 避免与 dashboard-edit.spec.ts 并行改写 seed「销售画布」产生竞态；模板也按唯一名清理。
 */

import { test, expect } from "../fixtures/auth";
import type { APIRequestContext, Page } from "@playwright/test";
import { apiCall, getAdminToken, getTableId, getWorkspaceId } from "../helpers/api";

const WS_NAME = "某企业销售管理";
const BASE_TABLE = "电商销售";
const OTHER_TABLE = "员工表";

interface ViewItem {
  id: number;
  name: string;
  view_type: string;
  view_options: Record<string, unknown> | null;
}

interface DashboardOptions {
  widgets?: Array<{
    id: string;
    type: string;
    query?: { table_id?: number; [key: string]: unknown };
    chart?: { x?: string; y?: string[]; [key: string]: unknown };
    kpi?: { value?: { field?: string; [key: string]: unknown }; [key: string]: unknown };
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}

interface TemplateItem {
  id: string;
  name: string;
  config: Record<string, unknown>;
  fields: Record<string, string>;
}

/** 统一的空查询口径（与 normalizeQuery 默认值一致） */
function emptyQuery(): Record<string, unknown> {
  return { filters: [], filter_logic: "AND", sortings: [] };
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

/** 创建 dashboard 视图（private 档，仅当前用户可见），返回落库后的视图 */
async function createDashboardView(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
  name: string,
  viewOptions: Record<string, unknown>,
): Promise<ViewItem> {
  const res = await apiCall(request, token, "post", `/workspaces/${wid}/tables/${tid}/views`, {
    name,
    view_type: "dashboard",
    view_options: viewOptions,
  });
  if (res.status !== 201) throw new Error(`创建视图失败：${res.status} ${JSON.stringify(res.body)}`);
  return res.body as ViewItem;
}

async function deleteView(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
  vid: number,
): Promise<void> {
  const res = await apiCall(request, token, "delete", `/workspaces/${wid}/tables/${tid}/views/${vid}`);
  if (res.status !== 204 && res.status !== 404) throw new Error(`删除视图失败：${res.status}`);
}

async function listTemplates(
  request: APIRequestContext,
  token: string,
): Promise<TemplateItem[]> {
  const res = await apiCall(request, token, "get", "/accounts/preferences/dashboard-templates");
  if (res.status !== 200) throw new Error(`读取模板失败：${res.status}`);
  return res.body as TemplateItem[];
}

async function deleteTemplatesByName(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<void> {
  const list = await listTemplates(request, token);
  for (const template of list.filter((t) => t.name === name)) {
    await apiCall(
      request,
      token,
      "delete",
      `/accounts/preferences/dashboard-templates/${encodeURIComponent(template.id)}`,
    );
  }
}

/** 打开指定 dashboard 视图页签并等待画布就绪 */
async function openView(page: Page, wid: number, tid: number, viewName: string) {
  await page.goto(`/w/${wid}/tables/${tid}`);
  const tab = page.locator('[data-testid^="view-tab-"]', { hasText: viewName });
  await expect(tab).toBeVisible({ timeout: 10_000 });
  await tab.scrollIntoViewIfNeeded();
  await tab.click();
  await expect(page.getByTestId("dashboard-canvas")).toBeVisible({ timeout: 10_000 });
}

/** 选择 antd Select 的某个选项（下拉在 body 上渲染，需单独定位） */
async function pickSelectOption(page: Page, selectTestId: string, optionText: string) {
  await page.getByTestId(selectTestId).click();
  await page
    .locator(".ant-select-dropdown:visible .ant-select-item-option", { hasText: optionText })
    .first()
    .click();
}

/** 读取视图最新的 view_options（轮询持久化结果用） */
async function readWidgets(
  request: APIRequestContext,
  token: string,
  wid: number,
  tid: number,
  vid: number,
): Promise<DashboardOptions["widgets"]> {
  const latest = (await listViews(request, token, wid, tid)).find((v) => v.id === vid);
  return (latest?.view_options as DashboardOptions | null)?.widgets;
}

/** 保存前定位到模板条目（item 是 role=button 的行） */
function templateItem(page: Page, name: string) {
  return page
    .getByTestId("dashboard-template-list")
    .locator('[role="button"]', { hasText: name })
    .first();
}

test.describe("dashboard P3", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(test.info().project.name === "chromium-anon", "anon 项目跳过");
    void page;
  });

  test("模板另存 → 从模板创建：同表往返后配置字段与组件保持", async ({ page, request }) => {
    const wid = await getWorkspaceId(request, WS_NAME);
    const tid = await getTableId(request, wid, BASE_TABLE);
    const token = await getAdminToken(request);
    const stamp = Date.now();
    const viewName = `P3 模板往返 ${stamp}`;
    const templateName = `P3 往返模板 ${stamp}`;

    const view = await createDashboardView(request, token, wid, tid, viewName, {
      schema_version: 1,
      widgets: [
        {
          id: "w_total",
          type: "kpi",
          title: "订单总数",
          layout: { x: 0, y: 0, w: 3, h: 4 },
          query: emptyQuery(),
          kpi: { value: { field: "订单号", agg: "count" } },
        },
        {
          id: "w_note",
          type: "text",
          title: "口径说明",
          layout: { x: 0, y: 4, w: 12, h: 3 },
          query: emptyQuery(),
          text: { content: "模板往返：只保存结构与字段快照" },
        },
      ],
      global_filters: [],
      settings: { refresh_interval: 0, theme: "inherit" },
    });

    try {
      await openView(page, wid, tid, viewName);

      // 另存为模板：剥离来源表后写入 per-user 偏好
      await page.getByTestId("dashboard-edit").click();
      await page.getByTestId("dashboard-template-save-open").click();
      const dialog = page.getByTestId("dashboard-template-dialog");
      await expect(dialog).toBeVisible({ timeout: 10_000 });
      await page.getByTestId("dashboard-template-name").fill(templateName);

      const saveResp = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().includes("/accounts/preferences/dashboard-templates"),
        { timeout: 10_000 },
      );
      await page.getByTestId("dashboard-template-save").click();
      const saved = await saveResp;
      expect(saved.status()).toBe(200);
      await expect(dialog).toBeHidden({ timeout: 10_000 });

      // 模板只存「结构 + 被引用字段的类型快照」，不含来源表
      const savedTemplate = (await listTemplates(request, token)).find((t) => t.name === templateName);
      expect(savedTemplate, "另存的模板应出现在列表中").toBeTruthy();
      expect(savedTemplate?.fields).toEqual({ 订单号: "text" });

      // 退出编辑（无未保存变更，直接回到只读工具栏）
      await page.getByTestId("dashboard-cancel").click();
      await expect(page.getByTestId("dashboard-edit")).toBeVisible({ timeout: 10_000 });

      // 从模板创建：选中刚保存的模板 → 应用 → 进入编辑态
      await page.getByTestId("dashboard-template-create").click();
      await expect(page.getByTestId("dashboard-template-list")).toBeVisible({ timeout: 10_000 });
      await templateItem(page, templateName).click();
      await expect(page.getByTestId("dashboard-template-apply")).toBeEnabled();
      await page.getByTestId("dashboard-template-apply").click();

      // 应用后整份替换草稿并进入编辑态，原组件 id 原样恢复
      await expect(page.getByTestId("dashboard-save")).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId("dashboard-card-w_total")).toBeVisible();
      await expect(page.getByTestId("dashboard-card-w_note")).toBeVisible();

      const patchResp = page.waitForResponse(
        (r) => r.request().method() === "PATCH" && r.url().includes(`/views/${view.id}`),
        { timeout: 10_000 },
      );
      await page.getByTestId("dashboard-save").click();
      const patched = await patchResp;
      expect(patched.status()).toBe(200);
      await expect(page.getByTestId("dashboard-edit")).toBeVisible({ timeout: 10_000 });

      await expect
        .poll(async () => (await readWidgets(request, token, wid, tid, view.id))?.map((w) => w.id), {
          timeout: 10_000,
        })
        .toEqual(["w_total", "w_note"]);
    } finally {
      await deleteTemplatesByName(request, token, templateName);
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("跨表数据来源：切换「员工表」后保存并走服务端取数", async ({ page, request }) => {
    const wid = await getWorkspaceId(request, WS_NAME);
    const tid = await getTableId(request, wid, BASE_TABLE);
    const empTid = await getTableId(request, wid, OTHER_TABLE);
    const token = await getAdminToken(request);
    const stamp = Date.now();
    const viewName = `P3 跨表 ${stamp}`;
    const templateName = `P3 跨表模板 ${stamp}`;

    const view = await createDashboardView(request, token, wid, tid, viewName, {
      schema_version: 1,
      widgets: [
        {
          id: "w_sum",
          type: "kpi",
          title: "合计值",
          layout: { x: 0, y: 0, w: 4, h: 4 },
          query: emptyQuery(),
          kpi: { value: { field: "销售额", agg: "sum" } },
        },
      ],
      global_filters: [],
      settings: { refresh_interval: 0, theme: "inherit" },
    });

    try {
      await openView(page, wid, tid, viewName);
      await page.getByTestId("dashboard-edit").click();
      await page.getByTestId("dashboard-properties").click();
      // 属性面板按需加载，等抽屉内的「数据」页签出现（页面导航也有同名 Tab，需限定抽屉）
      const dataTab = page.locator(".ant-drawer .ant-tabs-tab-btn", { hasText: "数据" });
      await expect(dataTab).toBeVisible({ timeout: 10_000 });
      await dataTab.click();

      // 切换数据来源表：字段按目标表 schema 重建（首选数值字段「薪资」）
      await pickSelectOption(page, "dashboard-source-table", OTHER_TABLE);
      await expect(page.getByTestId("dashboard-kpi-field")).toContainText("薪资", { timeout: 10_000 });

      await page.locator(".ant-drawer-close").click();
      await expect(dataTab).toBeHidden({ timeout: 10_000 });

      const patchResp = page.waitForResponse(
        (r) => r.request().method() === "PATCH" && r.url().includes(`/views/${view.id}`),
        { timeout: 10_000 },
      );
      await page.getByTestId("dashboard-save").click();
      expect((await patchResp).status()).toBe(200);

      // 落库配置：query.table_id 指向员工表，指标字段为数值字段「薪资」
      await expect
        .poll(async () => {
          const widget = (await readWidgets(request, token, wid, tid, view.id))?.find((w) => w.id === "w_sum");
          return [widget?.query?.table_id, widget?.kpi?.value?.field];
        }, { timeout: 10_000 })
        .toEqual([empTid, "薪资"]);

      // 重新打开：跨表 widget 触发服务端批量取数，KPI 显示员工表薪资合计
      const dataReq = page.waitForRequest(
        (r) => r.method() === "POST" && r.url().includes(`/views/${view.id}/dashboard/data`),
        { timeout: 15_000 },
      );
      await openView(page, wid, tid, viewName);
      await dataReq;
      await expect(page.getByTestId("dashboard-kpi-value-w_sum")).toContainText("148,500", {
        timeout: 10_000,
      });
      await expect(page.getByTestId("dashboard-widget-w_sum-error")).toHaveCount(0);

      // 另存模板：模板不含来源表，但保留被引用字段的类型快照
      await page.getByTestId("dashboard-edit").click();
      await page.getByTestId("dashboard-template-save-open").click();
      await expect(page.getByTestId("dashboard-template-dialog")).toBeVisible({ timeout: 10_000 });
      await page.getByTestId("dashboard-template-name").fill(templateName);
      const saveResp = page.waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().includes("/accounts/preferences/dashboard-templates"),
        { timeout: 10_000 },
      );
      await page.getByTestId("dashboard-template-save").click();
      expect((await saveResp).status()).toBe(200);

      const template = (await listTemplates(request, token)).find((t) => t.name === templateName);
      expect(template, "另存的模板应出现在列表中").toBeTruthy();
      const templateWidgets = (template?.config.widgets as DashboardOptions["widgets"]) ?? [];
      expect(templateWidgets).toHaveLength(1);
      // 模板只保存结构：跨表 widget 的来源表在落库前被剥离
      expect(templateWidgets[0]?.query?.table_id).toBeUndefined();
      // 跨表 widget 的引用字段按目标表 schema 补录类型快照（基表无「薪资」）
      expect(template?.fields["薪资"]).toBe("number");
    } finally {
      await deleteTemplatesByName(request, token, templateName);
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("全局筛选：{{global.x}} 未应用标记随取值消失，清除后复现", async ({ page, request }) => {
    const wid = await getWorkspaceId(request, WS_NAME);
    const tid = await getTableId(request, wid, BASE_TABLE);
    const token = await getAdminToken(request);
    const viewName = `P3 全局筛选 ${Date.now()}`;

    const view = await createDashboardView(request, token, wid, tid, viewName, {
      schema_version: 1,
      widgets: [
        {
          id: "w_cat",
          type: "chart",
          title: "类别销售额",
          layout: { x: 0, y: 0, w: 12, h: 8 },
          query: {
            filters: [{ field_name: "商品类别", op: "in", value: "{{global.cat}}" }],
            filter_logic: "AND",
            sortings: [],
          },
          chart: {
            type: "bar",
            x: "商品类别",
            y: ["销售额"],
            agg: "sum",
            stack: "none",
            sort: "none",
            dual_axis: false,
            format: {},
          },
        },
      ],
      global_filters: [{ id: "cat", kind: "select", field: "商品类别", label: "类别" }],
      settings: { refresh_interval: 0, theme: "inherit" },
    });

    const meta = page.getByTestId("dashboard-widget-w_cat-meta");

    try {
      await openView(page, wid, tid, viewName);
      await expect(page.getByTestId("dashboard-globals")).toBeVisible();
      await expect(page.getByTestId("dashboard-global-cat")).toBeVisible();
      // 未取值时占位符条件被剔除并计入 unapplied
      await expect(meta).toContainText("未应用全局筛选");

      // tags 选择：输入后回车成标签，值注入 filters
      const select = page.getByTestId("dashboard-global-cat");
      await select.click();
      await select.locator("input").fill("数码");
      await page.keyboard.press("Enter");
      await page.keyboard.press("Escape");
      await expect(meta).not.toContainText("未应用全局筛选", { timeout: 10_000 });

      // 清除筛选后条件再次被剔除，未应用标记复现
      await page.getByTestId("dashboard-globals-reset").click();
      await expect(meta).toContainText("未应用全局筛选", { timeout: 10_000 });
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("定时刷新：refresh_interval=2 时按周期重新拉取行集", async ({ page, request }) => {
    const wid = await getWorkspaceId(request, WS_NAME);
    const tid = await getTableId(request, wid, BASE_TABLE);
    const token = await getAdminToken(request);
    const viewName = `P3 定时刷新 ${Date.now()}`;

    const view = await createDashboardView(request, token, wid, tid, viewName, {
      schema_version: 1,
      widgets: [
        {
          id: "w_total",
          type: "kpi",
          title: "订单总数",
          layout: { x: 0, y: 0, w: 3, h: 4 },
          query: emptyQuery(),
          kpi: { value: { field: "订单号", agg: "count" } },
        },
      ],
      global_filters: [],
      settings: { refresh_interval: 2, theme: "inherit" },
    });

    // 小表路径：定时刷新由页面层重新拉行集（GET /records）
    let recordRequests = 0;
    page.on("request", (r) => {
      if (r.method() === "GET" && r.url().includes(`/tables/${tid}/records`)) recordRequests += 1;
    });

    try {
      await openView(page, wid, tid, viewName);
      await expect(page.getByText("每 2s 自动刷新")).toBeVisible();
      await expect(page.getByTestId("dashboard-kpi-w_total")).toBeVisible();
      await expect(page.getByTestId("dashboard-widget-w_total-error")).toHaveCount(0);

      const initial = recordRequests;
      await expect
        .poll(() => recordRequests, { timeout: 20_000 })
        .toBeGreaterThan(initial);
    } finally {
      await deleteView(request, token, wid, tid, view.id);
    }
  });

  test("模板缺字段：为目标表逐项映射后保存改写字段", async ({ page, request }) => {
    const wid = await getWorkspaceId(request, WS_NAME);
    const empTid = await getTableId(request, wid, OTHER_TABLE);
    const token = await getAdminToken(request);
    const stamp = Date.now();
    const viewName = `P3 缺字段 ${stamp}`;
    const templateName = `P3 缺字段模板 ${stamp}`;

    // 目标视图落在员工表，只含说明组件（占位，等待模板整份替换）
    const view = await createDashboardView(request, token, wid, empTid, viewName, {
      schema_version: 1,
      widgets: [
        {
          id: "w_note",
          type: "text",
          title: "说明",
          layout: { x: 0, y: 0, w: 12, h: 4 },
          query: emptyQuery(),
          text: { content: "在员工表上应用来自电商销售的模板" },
        },
      ],
      global_filters: [],
      settings: { refresh_interval: 0, theme: "inherit" },
    });

    // 模板来自电商销售字段：商品类别(text) / 销售额(number)，员工表无同名同类型字段
    const templateResp = await apiCall(request, token, "post", "/accounts/preferences/dashboard-templates", {
      name: templateName,
      config: {
        schema_version: 1,
        widgets: [
          {
            id: "w_sales",
            type: "chart",
            title: "类别销售额",
            layout: { x: 0, y: 0, w: 12, h: 8 },
            query: emptyQuery(),
            chart: {
              type: "bar",
              x: "商品类别",
              y: ["销售额"],
              agg: "sum",
              stack: "none",
              sort: "none",
              dual_axis: false,
              format: {},
            },
          },
        ],
        global_filters: [],
        settings: { refresh_interval: 0, theme: "inherit" },
      },
      fields: { 商品类别: "text", 销售额: "number" },
    });
    expect(templateResp.status).toBe(200);

    try {
      await openView(page, wid, empTid, viewName);
      await page.getByTestId("dashboard-template-create").click();
      await expect(page.getByTestId("dashboard-template-list")).toBeVisible({ timeout: 10_000 });
      await templateItem(page, templateName).click();

      // 两个字段都认领失败，逐项指定目标字段（同名同类型优先）
      await expect(page.getByTestId("dashboard-template-map-商品类别")).toBeVisible();
      await pickSelectOption(page, "dashboard-template-map-商品类别", "姓名");
      await pickSelectOption(page, "dashboard-template-map-销售额", "薪资");
      await expect(page.getByTestId("dashboard-template-apply")).toBeEnabled();

      await page.getByTestId("dashboard-template-apply").click();
      await expect(page.getByTestId("dashboard-save")).toBeVisible({ timeout: 10_000 });

      const patchResp = page.waitForResponse(
        (r) => r.request().method() === "PATCH" && r.url().includes(`/views/${view.id}`),
        { timeout: 10_000 },
      );
      await page.getByTestId("dashboard-save").click();
      expect((await patchResp).status()).toBe(200);

      // 落库配置已按映射改写字段引用
      await expect
        .poll(async () => {
          const widget = (await readWidgets(request, token, wid, empTid, view.id))?.find((w) => w.id === "w_sales");
          return [widget?.chart?.x, widget?.chart?.y];
        }, { timeout: 10_000 })
        .toEqual(["姓名", ["薪资"]]);
    } finally {
      await deleteTemplatesByName(request, token, templateName);
      await deleteView(request, token, wid, empTid, view.id);
    }
  });
});
